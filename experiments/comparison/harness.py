#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private comparison transport. No installation or production imports."""
import hashlib
import errno
import fcntl
import json
import os
from pathlib import Path
import selectors
import struct
import subprocess
import sys
import tempfile
import threading
import traceback
import time
import uuid

from runtime_bundle import validate, host_environment, digest, MANIFEST
import runtime_evidence

INPUT_LIMIT = 256 * 1024 * 1024
OUTPUT_LIMIT = INPUT_LIMIT
CONTROL_LIMIT = 65536


def snapshot(device, limit=INPUT_LIMIT):
    """Seek caller-owned device to zero; check actual bytes, never trust size()."""
    device.seek(0)
    result = bytearray()
    while True:
        block = device.read(min(65536, limit + 1 - len(result)))
        if block is None:
            raise OSError("read failed")
        if not block:
            return bytes(result)
        result.extend(block)
        if len(result) > limit:
            raise ValueError("input limit")


class RequestCancelled(RuntimeError):
    """The request was discarded and its scope was verified empty."""


class CleanupError(RuntimeError):
    """Terminal cleanup failed; diagnostics retain the triggering error."""


def validate_paths(paths):
    if not isinstance(paths, list) or len(paths) > 256:
        raise ValueError("reference count")
    if len(json.dumps(dict(paths=paths), ensure_ascii=False).encode()) > CONTROL_LIMIT:
        raise ValueError("manifest control limit")
    unique = set()
    for path in paths:
        if (not isinstance(path, str) or not path or len(path.encode('utf-8')) > 1024
                or path != path.strip() or any(c in path for c in '%\\?#:\x00')
                or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or any(part in ('', '.', '..') for part in path.split('/'))):
            raise ValueError("invalid relative resource path")
        unique.add(path)
    names = unique | {'main.svg'}
    if 'main.svg' in unique or any('/'.join(path.split('/')[:i]) in names
                                 for path in names for i in range(1, len(path.split('/')))):
        raise ValueError("capsule staging collision")
    return sorted(unique)


def validate_file_map(files):
    if not isinstance(files, dict) or 'main.svg' not in files:
        raise ValueError("captured main missing")
    validate_paths([name for name in files if name != 'main.svg'])
    if (any(type(data) is not bytes for data in files.values())
            or len(files['main.svg']) > 10 * 1024 * 1024
            or sum(map(len, files.values())) > INPUT_LIMIT):
        raise ValueError("captured file limit")


def recorded_constructor(function):
    def construct(self, binary, *args, **kwargs):
        invocation = runtime_evidence.ACTIVE
        self.evidence = invocation.begin_scope(binary) if invocation else None
        self.invocation = invocation
        try:
            return function(self, binary, *args, **kwargs)
        except BaseException as error:
            if self.evidence is not None:
                self.evidence['constructor_error'] = repr(error)
                if self.evidence['phase'] == 'preflight':
                    self.evidence['phase'] = 'preflight-rejected'
                invocation.checkpoint()
            raise
    return construct


class Worker:
    @recorded_constructor
    def __init__(self, binary, isolated=True, capsule=None, glycin=False, trace=None, arguments=(), diagnostic=None, captured_files=None, runtime_bundle=None, environment=None, sandbox_executable='/usr/bin/bwrap'):
        if capsule is not None and captured_files is not None:
            raise ValueError("capsule and captured_files are mutually exclusive")
        if captured_files is not None:
            validate_file_map(captured_files)
            if not isolated:
                raise ValueError("captured files require isolation")
        self.binary = Path(binary).resolve()
        selected = runtime_bundle or (self.invocation.runtime_bundle if self.invocation else None)
        bundle = Path(selected) if selected is not None else self.binary.parent / 'runtime-bundle'
        if isolated:
            manifest, entry = validate(bundle, self.binary, glycin)
            bundle = bundle.resolve()
        if self.evidence is not None:
            self.evidence['binary_sha256'] = digest(self.binary)
            if isolated:
                self.evidence.update(manifest_sha256=digest(bundle / MANIFEST), entry=entry)
        self._lock = threading.RLock()
        self._cancel_event = None
        self.diagnostic = diagnostic
        self.terminal = False
        self.cleanup = None
        self._cleanup_error = None
        self._closed = False
        self.temporary = tempfile.TemporaryDirectory(prefix="image-comparison-")
        self.stderr = tempfile.TemporaryFile()
        self.peak_rss_kib = 0
        self.memory_series = []
        self.scope_empty = False
        self.operation_deadline = None
        self.traced = trace is not None
        self.graceful_close = False
        self.sampled_pids = set()
        self.copied_bytes = 0
        self.cpu_us = 0
        self.cgroup = None
        capsule_sources = []
        command = [str(self.binary), *map(str, arguments)]
        if isolated:
            command = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session",
                       "--clearenv", "--setenv", "PATH", "/usr/bin", "--setenv", "HOME", "/tmp",
                       "--setenv", "QT_PLUGIN_PATH", "/usr/lib/qt6/plugins",
                       "--setenv", "QT_IMAGEIO_MAXALLOC", "256", "--proc", "/proc", "--dev", "/dev",
                       "--tmpfs", "/tmp", "--dir", "/run", "--dir", "/usr/lib", "--symlink", "usr/lib", "/lib",
                       "--symlink", "usr/lib", "/lib64"]
            command += ['--ro-bind', str(bundle / 'usr/share/mime'), '/usr/share/mime']
            for record in manifest['files']:
                if record['destination'].startswith('/usr/share/mime/'):
                    continue
                command += ['--ro-bind', str(bundle / record['path']), record['destination']]
            if glycin:
                command += ['--setenv', 'GLYCIN_DATA_DIR', '/configuration',
                            '--setenv', 'XDG_DATA_DIRS', '/usr/share',
                            '--setenv', 'XDG_DATA_HOME', '/nonexistent']
            if captured_files is not None:
                command += ["--dir", "/capsule"]
                directories = set()
                for name, data in sorted(captured_files.items()):
                    for directory in Path(name).parents:
                        if str(directory) != ".":
                            directories.add(str(directory))
                for directory in sorted(directories, key=lambda value: (value.count('/'), value)):
                    command += ["--dir", "/capsule/" + directory]
                for name, data in sorted(captured_files.items()):
                    staged = Path(self.temporary.name) / f"capsule-{len(capsule_sources)}"
                    staged.write_bytes(data)
                    command += ["--ro-bind-data", f"@capsule:{len(capsule_sources)}", "/capsule/" + name]
                    capsule_sources.append(str(staged))
            if capsule:
                command += ["--dir", "/capsule"]
                total = 0
                entries = sorted(Path(capsule).rglob("*"))
                if len(entries) > 4096:
                    raise ValueError("capsule entry limit")
                for path in entries:
                    target = "/capsule/" + str(path.relative_to(capsule))
                    if path.is_symlink():
                        command += ["--symlink", os.readlink(path), target]
                    elif path.is_dir():
                        command += ["--dir", target]
                    elif path.is_file():
                        with path.open("rb") as source:
                            data = snapshot(source, INPUT_LIMIT - total)
                        total += len(data)
                        staged = Path(self.temporary.name) / f"capsule-{len(capsule_sources)}"
                        staged.write_bytes(data)
                        command += ["--ro-bind-data", f"@capsule:{len(capsule_sources)}", target]
                        capsule_sources.append(str(staged))
            command += ["--", entry["destination"], *map(str, arguments)]
        if isolated and sandbox_executable != '/usr/bin/bwrap':
            command[0] = str(sandbox_executable)
            command = ['/usr/bin/env', *command]
        if trace:
            command = ["/usr/bin/strace", "-f", "--seccomp-bpf", "-e", "inject=exit_group:delay_enter=100ms", "-n", "--decode-pids=pidns", "-v", "-s", "65535", "-yy", "-e", "trace=process,network,file,dup,dup2,dup3,fcntl,close,fchdir", "-o", str(trace), *command]
        self.runtime_command = command
        launch = Path(self.temporary.name) / "launch.json"
        release = Path(self.temporary.name) / "release"
        launch_environment = host_environment() if environment is None else dict(environment)
        launch.write_text(json.dumps(dict(command=command, sources=capsule_sources,
                                         release=str(release), environment=launch_environment)))
        command = [sys.executable, str(Path(__file__).resolve()), str(launch)]
        self.unit = "image-comparison-" + uuid.uuid4().hex + ".scope"
        command = ["/usr/bin/systemd-run", "--user", "--scope", "--quiet", "--unit=" + self.unit,
                   "--property=MemoryMax=2G", "--property=MemorySwapMax=0", *command]
        self.launch_command = command
        self.runtime_manifest = manifest if isolated else None
        self.started = time.monotonic()
        if self.evidence is not None:
            self.evidence.update(phase='launch-intent', unit=self.unit, command=command,
                                 runtime_command=self.runtime_command, environment=launch_environment,
                                 launcher_environment=host_environment())
            self.invocation.checkpoint()
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.stderr, start_new_session=True, bufsize=0,
                                            close_fds=True, env=host_environment())
            if self.evidence is not None:
                self.evidence['launcher_pid'] = self.process.pid
                self.invocation.checkpoint()
        except BaseException as error:
            if self.evidence is not None:
                self.evidence.update(phase='launcher-failed', error=repr(error))
                self.invocation.checkpoint()
            self.stderr.close()
            self.temporary.cleanup()
            raise
        try:
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
            deadline = time.monotonic() + 5
            while self.cgroup is None:
                self.sample()
                if self.process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('scope startup failed: ' + os.pread(self.stderr.fileno(), 65536, 0).decode(errors='replace'))
                time.sleep(.005)
            release.write_text('observed limits')
        except BaseException:
            try:
                self.abort()
            finally:
                self.stderr.close()
                self.process.stdin.close()
                self.process.stdout.close()
                self.temporary.cleanup()
            raise

    def sample(self):
        try:
            if self.cgroup is None:
                entries = Path(f"/proc/{self.process.pid}/cgroup").read_text().splitlines()
                for entry in entries:
                    if entry.startswith("0::") and entry.endswith(self.unit):
                        self.cgroup = Path("/sys/fs/cgroup") / entry[3:].lstrip("/")
            if self.cgroup:
                if self.evidence is not None and 'memory_max' not in self.evidence:
                    self.evidence.update(phase='created', cgroup=str(self.cgroup),
                        memory_max=(self.cgroup / 'memory.max').read_text().strip(),
                        swap_max=(self.cgroup / 'memory.swap.max').read_text().strip())
                    self.invocation.checkpoint()
                if (self.cgroup / "memory.max").read_text().strip() != str(2 * 1024**3):
                    raise RuntimeError("process-tree memory ceiling missing")
                if (self.cgroup / "memory.swap.max").read_text().strip() != "0":
                    raise RuntimeError("process-tree swap limit missing")
                pids = [int(p) for p in (self.cgroup / "cgroup.procs").read_text().split()]
                self.sampled_pids.update(pids)
                rss = 0
                for pid in pids:
                    try:
                        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                            if line.startswith("VmRSS:"):
                                rss += int(line.split()[1])
                    except FileNotFoundError:
                        pass
                self.peak_rss_kib = max(self.peak_rss_kib, rss)
                cpu = dict(line.split() for line in (self.cgroup / "cpu.stat").read_text().splitlines())
                self.cpu_us = int(cpu["usage_usec"])
                memory = dict(line.split() for line in (self.cgroup / "memory.stat").read_text().splitlines())
                point = dict(timestamp=time.monotonic(), rss_bytes=rss * 1024,
                             anonymous_bytes=int(memory["anon"]),
                             memory_current_bytes=int((self.cgroup / "memory.current").read_text()),
                             process_count=len(pids))
                self.memory_series.append(point)
                return point
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ENODEV, errno.ESRCH):
                raise

    def checkpoint(self, phase):
        if self.diagnostic:
            self.diagnostic(phase)
        if self._cancel_event is not None and self._cancel_event.is_set():
            if not hasattr(self, "cancel_observed"):
                self.cancel_observed = time.monotonic()
            raise RequestCancelled("request cancelled at " + phase)

    def transfer(self, size=None, outgoing=None, deadline=None):
        deadline = deadline or time.monotonic() + 15
        data = bytearray()
        offset = 0
        with selectors.DefaultSelector() as selector:
            stream = self.process.stdin if outgoing is not None else self.process.stdout
            selector.register(stream, selectors.EVENT_WRITE if outgoing is not None else selectors.EVENT_READ)
            while (offset < len(outgoing)) if outgoing is not None else (len(data) < size):
                self.checkpoint("transfer-write" if outgoing is not None else "transfer-read")
                if time.monotonic() >= deadline:
                    raise TimeoutError("15 second operation timeout")
                self.sample()
                if not selector.select(min(.01, max(0, deadline - time.monotonic()))):
                    self.checkpoint("blocked-write" if outgoing is not None else "blocked-read")
                    continue
                if outgoing is not None:
                    try:
                        written = os.write(stream.fileno(), outgoing[offset:offset + 65536])
                    except BlockingIOError:
                        continue
                    offset += written
                    self.checkpoint("write-progress")
                else:
                    try:
                        block = os.read(stream.fileno(), min(65536, size - len(data)))
                    except BlockingIOError:
                        continue
                    if not block:
                        error = os.pread(self.stderr.fileno(), 65536, 0).decode(errors="replace")
                        raise RuntimeError("worker EOF: " + error)
                    data.extend(block)
                    self.checkpoint("read-progress")
        return bytes(data)

    def request(self, op, payload=b"", capture_pixels=False, *, cancel_event=None, **fields):
        with self._lock:
            if self.terminal or self._closed:
                raise RuntimeError("terminal worker; construct a fresh worker")
            self._cancel_event = cancel_event
            try:
                self.checkpoint("before-transfer")
                return self._request(op, payload, capture_pixels, **fields)
            except Exception as error:
                # Cancellation wins over simultaneous EOF, malformed replies and timeout.
                if not isinstance(error, RequestCancelled):
                    try:
                        self.checkpoint("request-error")
                    except RequestCancelled as cancelled:
                        error = cancelled
                if isinstance(error, RequestCancelled):
                    traceback.clear_frames(error.__traceback__)
                    if error.__context__ is not None:
                        traceback.clear_frames(error.__context__.__traceback__)
                try:
                    self.abort()
                except CleanupError as cleanup:
                    raise CleanupError(f"{type(error).__name__}: {error}; {cleanup}") from error
                raise error
            finally:
                self._cancel_event = None

    def _request(self, op, payload=b"", capture_pixels=False, **fields):
        if len(payload) > INPUT_LIMIT:
            raise ValueError("input limit")
        record = json.dumps(dict(op=op, bytes=len(payload), **fields), separators=(",", ":")).encode()
        if len(record) > CONTROL_LIMIT:
            raise ValueError("control limit")
        deadline = time.monotonic() + 15
        if self.operation_deadline is not None:
            deadline = min(deadline, self.operation_deadline)
        self.transfer(outgoing=struct.pack(">I", len(record)) + record + payload, deadline=deadline)
        self.checkpoint("dispatched")
        length, = struct.unpack(">I", self.transfer(size=4, deadline=deadline))
        self.checkpoint("response-header")
        if not 0 < length <= CONTROL_LIMIT:
            raise ValueError("response control limit")
        control = json.loads(self.transfer(size=length, deadline=deadline))
        self.checkpoint("response-control")
        if not isinstance(control, dict):
            raise ValueError("response must be an object")
        size = control.get("bytes")
        if type(size) is not int or not 0 <= size <= OUTPUT_LIMIT:
            raise ValueError("response byte limit")
        if size:
            width, height, stride = (control.get(k) for k in ("width", "height", "stride"))
            if any(type(v) is not int for v in (width, height, stride)) or not (
                    0 < width <= 32768 and 0 < height <= 32768 and width * height <= 64000000
                    and stride == width * 4 and size == stride * height):
                raise ValueError("response pixel layout")
        self.checkpoint("before-pixels")
        pixels = self.transfer(size=size, deadline=deadline)
        self.copied_bytes += len(payload) + len(pixels)
        control["pixel_sha256"] = hashlib.sha256(pixels).hexdigest() if pixels else None
        control["first_pixel"] = list(pixels[:4])
        if capture_pixels:
            control["pixels"] = list(pixels)
        self.checkpoint("before-result")
        return control

    def _manager(self, arguments, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("cleanup deadline exhausted")
        started = time.monotonic()
        try:
            result = subprocess.run(["/usr/bin/systemctl", "--user", *arguments], capture_output=True,
                                    text=True, timeout=remaining, env=host_environment())
        except Exception as error:
            self.cleanup["manager"].append(dict(arguments=arguments, started=started,
                                                completed=time.monotonic(), error=repr(error)))
            raise
        self.cleanup["manager"].append(dict(arguments=arguments, started=started,
                                            completed=time.monotonic(), returncode=result.returncode,
                                            stdout=result.stdout, stderr=result.stderr))
        if result.returncode and arguments[0] == "show" and any(
                text in result.stderr for text in ("not found", "not loaded")):
            return ""
        if (result.returncode and arguments[0] == "kill" and "not loaded" in result.stderr
                and self._scope_empty()):
            # EOF may remove the unit between the populated check and the signal.
            return ""
        if result.returncode:
            raise RuntimeError("scope manager failed: " + result.stderr)
        return result.stdout.strip()

    def _scope_empty(self):
        if self.cgroup is None:
            return False
        try:
            # cgroup.events populated includes all descendants, unlike cgroup.procs.
            events = dict(line.split() for line in (self.cgroup / "cgroup.events").read_text().splitlines())
            self.cleanup["cgroup_events"] = events
            return events.get("populated") == "0"
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ENODEV):
                raise
            removed = not self.cgroup.exists()
            self.cleanup["cgroup_removed"] = removed
            return removed

    def abort(self):
        with self._lock:
            if self.cleanup is not None:
                if self._cleanup_error:
                    raise CleanupError(self._cleanup_error)
                return
            self.terminal = True
            started = time.monotonic()
            deadline = getattr(self, "cancel_observed", started) + 5
            self.cleanup = dict(started=started, manager=[], unit=self.unit)
            try:
                if self.traced and self.graceful_close:
                    # Let traced exit_group delay and asynchronous loader shutdown
                    # finish inside this same five-second cleanup budget.
                    try:
                        self.process.wait(timeout=min(.5, max(.001, deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        pass

                if self.cgroup is None:
                    # A pre-dispatch cancellation can precede scope registration.
                    resolve_deadline = min(deadline, started + 1)
                    while self.cgroup is None:
                        group = self._manager(["show", "--property=ControlGroup", "--value", self.unit], deadline)
                        if group:
                            path = Path("/sys/fs/cgroup") / group.lstrip("/")
                            if path.name != self.unit or ".." in path.parts:
                                raise RuntimeError("invalid scope identity")
                            self.cgroup = path
                        elif self.process.poll() is not None:
                            state = self._manager(['show', '--property=LoadState', '--value', self.unit], deadline)
                            if state in ('', 'not-found'):
                                self.process.wait(timeout=max(.001, deadline - time.monotonic()))
                                self.cleanup['unit_absent'] = True
                                self.scope_empty = True
                                return
                            raise RuntimeError('scope has no cgroup; cleanup unverified')
                        elif time.monotonic() >= resolve_deadline:
                            raise RuntimeError("scope identity unavailable; cleanup unverified")
                        else:
                            time.sleep(min(.01, max(0, resolve_deadline - time.monotonic())))
                if self.evidence is not None and 'memory_max' not in self.evidence and self.cgroup.exists():
                    self.evidence.update(phase='created', cgroup=str(self.cgroup),
                        memory_max=(self.cgroup / 'memory.max').read_text().strip(),
                        swap_max=(self.cgroup / 'memory.swap.max').read_text().strip())
                self.cleanup["cgroup"] = str(self.cgroup)
                if not self._scope_empty():
                    self._manager(["kill", "--signal=TERM", self.unit], deadline)
                    grace = min(deadline, time.monotonic() + 1)
                    while not self._scope_empty() and time.monotonic() < grace:
                        time.sleep(min(.01, max(0, grace - time.monotonic())))
                    if not self._scope_empty():
                        self._manager(["kill", "--signal=KILL", self.unit], deadline)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("cleanup deadline exhausted")
                self.process.wait(timeout=remaining)
                while not self._scope_empty():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("scope remained populated")
                    time.sleep(min(.01, remaining))
                if time.monotonic() >= deadline:
                    raise TimeoutError("cleanup deadline exhausted")
                self.scope_empty = True
            except Exception as error:
                self._cleanup_error = str(error)
                raise CleanupError(self._cleanup_error) from error
            finally:
                if self.process.poll() is None:
                    self.process.kill()
                    try:
                        self.process.wait(timeout=max(.001, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        self._cleanup_error = 'launcher reaping unverified'
                self.cleanup.update(completed=time.monotonic(), launcher_status=self.process.poll(),
                                    scope_empty=self.scope_empty)
                if self.evidence is not None:
                    self.evidence.setdefault('cleanup_attempts', []).append(dict(self.cleanup))
                    self.evidence['cleanup'] = dict(self.cleanup)
                    if self.cleanup.get('unit_absent') and self.evidence['phase'] != 'created':
                        self.evidence['phase'] = 'absent'
                    self.invocation.checkpoint()

    def close(self):
        with self._lock:
            if self._closed:
                return self._stderr_text
            try:
                if not self.terminal and self.process.poll() is None:
                    self.request("close")
                    self.graceful_close = True
                if not self.terminal:
                    self.abort()
            finally:
                self._stderr_text = os.pread(self.stderr.fileno(), 65536, 0).decode(errors="replace")
                self.stderr.close()
                self.process.stdin.close()
                self.process.stdout.close()
                self.temporary.cleanup()
                self._closed = True
            return self._stderr_text


if __name__ == "__main__":
    launch = json.loads(Path(sys.argv[1]).read_text())
    deadline = time.monotonic() + 10
    while not Path(launch['release']).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('scope release deadline')
        time.sleep(.005)
    descriptors = []
    for source in launch["sources"]:
        fd = os.memfd_create("comparison-capsule", os.MFD_ALLOW_SEALING)
        with open(source, "rb") as stream, os.fdopen(os.dup(fd), "wb") as destination:
            destination.write(snapshot(stream))
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW |
                    fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        os.lseek(fd, 0, os.SEEK_SET)
        os.set_inheritable(fd, True)
        descriptors.append(fd)
    command = [str(descriptors[int(arg.split(':')[1])]) if arg.startswith("@capsule:") else arg
               for arg in launch["command"]]
    os.execve(command[0], command, launch['environment'])
