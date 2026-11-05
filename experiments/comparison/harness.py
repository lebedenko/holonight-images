#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private comparison transport. No installation or production imports."""
import hashlib
import functools
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import sys
import tempfile
import time
import uuid

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


def libraries(paths):
    result = set()
    for path in paths:
        output = subprocess.check_output(["ldd", str(path)], text=True)
        for line in output.splitlines():
            for word in line.split():
                if word.startswith("/"):
                    result.add(Path(word))
    return sorted(result)


@functools.cache
def runtime(binary, glycin=False):
    """Explicit codec plugin set, then the dynamic-linker dependency closure."""
    root = Path("/usr/lib/qt6/plugins/imageformats")
    plugins = [root / name for name in ("libqgif.so", "libqjpeg.so", "libqsvg.so",
                                        "libqtiff.so", "libqwebp.so")]
    paths = [binary, *plugins]
    if glycin:
        paths += [Path("/usr/bin/bwrap"), Path("/usr/bin/xdg-dbus-proxy")]
        paths = [p for p in paths if p.exists()]
        paths += [Path("/usr/lib/glycin-loaders/2+/glycin-image-rs"),
                  Path("/usr/lib/glycin-loaders/2+/glycin-svg")]
    return sorted(set(paths + libraries(paths)))


class Worker:
    def __init__(self, binary, isolated=True, capsule=None, glycin=False, trace=None, arguments=()):
        self.temporary = tempfile.TemporaryDirectory(prefix="image-comparison-")
        self.binary = Path(binary).resolve()
        self.stderr = tempfile.TemporaryFile()
        self.peak_rss_kib = 0
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
            for path in runtime(self.binary, glycin):
                command += ["--ro-bind", str(path), str(path)]
            if glycin:
                config = Path(self.temporary.name) / "glycin-loaders/2+/conf.d"
                config.mkdir(parents=True)
                # Only the existing seven raster/SVG contract MIME types are discoverable.
                text = ""
                for name, signature in (("png", r"0:\\x89PNG"), ("jpeg", r"0:\\xFF\\xD8\\xFF"),
                                        ("gif", "0:GIF8"), ("bmp", "0:BM"),
                                        ("webp", "0:RIFF,8:WEBP"), ("tiff", r"0:II\\x2a\\x00;0:MM\\x00\\x2a")):
                    text += f"[loader:image/{name}]\nExec=/usr/lib/glycin-loaders/2+/glycin-image-rs\nIdentifiers={signature};\n\n"
                text += "[loader:image/svg+xml]\nExec=/usr/lib/glycin-loaders/2+/glycin-svg\nIdentifiers=ext:svg;\nExposeBaseDir=true\n\n"
                (config / "comparison.conf").write_text(text)
                command += ["--ro-bind", str(Path(self.temporary.name)), "/configuration",
                            "--setenv", "GLYCIN_DATA_DIR", "/configuration",
                            "--setenv", "XDG_DATA_DIRS", "/usr/share",
                            "--setenv", "XDG_DATA_HOME", "/nonexistent"]
                # MIME detection data, separate from executable discovery.
                command += ["--ro-bind", "/usr/share/mime", "/usr/share/mime"]
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
            command += ["--", str(self.binary), *map(str, arguments)]
        if trace:
            command = ["strace", "-f", "-e", "trace=process,network,file", "-o", str(trace), *command]
        if capsule_sources:
            launch = Path(self.temporary.name) / "launch.json"
            launch.write_text(json.dumps(dict(command=command, sources=capsule_sources)))
            # Seal after systemd-run, whose scope launcher closes inherited descriptors.
            command = [sys.executable, str(Path(__file__).resolve()), str(launch)]
        self.unit = "image-comparison-" + uuid.uuid4().hex + ".scope"
        command = ["systemd-run", "--user", "--scope", "--quiet", "--unit=" + self.unit,
                   "--property=MemoryMax=2G", "--property=MemorySwapMax=0", *command]
        self.started = time.monotonic()
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, start_new_session=True, bufsize=0,
                                        close_fds=True)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)

    def sample(self):
        try:
            if self.cgroup is None:
                entries = Path(f"/proc/{self.process.pid}/cgroup").read_text().splitlines()
                for entry in entries:
                    if entry.startswith("0::") and entry.endswith(self.unit):
                        self.cgroup = Path("/sys/fs/cgroup") / entry[3:].lstrip("/")
            if self.cgroup:
                if (self.cgroup / "memory.max").read_text().strip() != str(2 * 1024**3):
                    raise RuntimeError("process-tree memory ceiling missing")
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
        except FileNotFoundError:
            pass

    def transfer(self, size=None, outgoing=None, deadline=None):
        deadline = deadline or time.monotonic() + 15
        data = bytearray()
        offset = 0
        with selectors.DefaultSelector() as selector:
            stream = self.process.stdin if outgoing is not None else self.process.stdout
            selector.register(stream, selectors.EVENT_WRITE if outgoing is not None else selectors.EVENT_READ)
            while (offset < len(outgoing)) if outgoing is not None else (len(data) < size):
                if time.monotonic() >= deadline:
                    self.abort()
                    raise TimeoutError("15 second operation timeout")
                self.sample()
                if not selector.select(min(.01, max(0, deadline - time.monotonic()))):
                    continue
                if outgoing is not None:
                    written = os.write(stream.fileno(), outgoing[offset:offset + 65536])
                    offset += written
                else:
                    block = os.read(stream.fileno(), min(65536, size - len(data)))
                    if not block:
                        error = os.pread(self.stderr.fileno(), 65536, 0).decode(errors="replace")
                        raise RuntimeError("worker EOF: " + error)
                    data.extend(block)
        return bytes(data)

    def request(self, op, payload=b"", capture_pixels=False, **fields):
        if len(payload) > INPUT_LIMIT:
            raise ValueError("input limit")
        record = json.dumps(dict(op=op, bytes=len(payload), **fields), separators=(",", ":")).encode()
        if len(record) > CONTROL_LIMIT:
            raise ValueError("control limit")
        deadline = time.monotonic() + 15
        self.transfer(outgoing=struct.pack(">I", len(record)) + record + payload, deadline=deadline)
        length, = struct.unpack(">I", self.transfer(size=4, deadline=deadline))
        if not 0 < length <= CONTROL_LIMIT:
            self.abort()
            raise ValueError("response control limit")
        control = json.loads(self.transfer(size=length, deadline=deadline))
        size = control.get("bytes")
        if type(size) is not int or not 0 <= size <= OUTPUT_LIMIT:
            self.abort()
            raise ValueError("response byte limit")
        if size:
            width, height, stride = (control.get(k) for k in ("width", "height", "stride"))
            if any(type(v) is not int for v in (width, height, stride)) or not (
                    0 < width <= 32768 and 0 < height <= 32768 and width * height <= 64000000
                    and stride == width * 4 and size == stride * height):
                self.abort()
                raise ValueError("response pixel layout")
        pixels = self.transfer(size=size, deadline=deadline)
        self.copied_bytes += len(payload) + len(pixels)
        control["pixel_sha256"] = hashlib.sha256(pixels).hexdigest() if pixels else None
        control["first_pixel"] = list(pixels[:4])
        if capture_pixels:
            control["pixels"] = list(pixels)
        return control

    def abort(self):
        # A process group also covers bwrap-created process sessions poorly; kill sampled descendants too.
        subprocess.run(["systemctl", "--user", "kill", "--signal=TERM", self.unit], capture_output=True, timeout=5)
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        subprocess.run(["systemctl", "--user", "kill", "--signal=KILL", self.unit], capture_output=True, timeout=5)
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=1)

    def close(self):
        if self.process.poll() is None:
            try:
                self.request("close")
                self.process.wait(timeout=1)
            except (OSError, RuntimeError, ValueError, TimeoutError, subprocess.TimeoutExpired):
                self.abort()
        self.stderr.seek(0)
        error = self.stderr.read(65536).decode(errors="replace")
        self.stderr.close()
        self.process.stdin.close()
        self.process.stdout.close()
        subprocess.run(["systemctl", "--user", "stop", self.unit], capture_output=True, timeout=5)
        self.temporary.cleanup()
        return error


if __name__ == "__main__":
    launch = json.loads(Path(sys.argv[1]).read_text())
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
    os.execv(command[0], command)
