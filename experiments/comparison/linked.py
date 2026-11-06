#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Experimental caller adapter for descriptor-pinned linked SVG acquisition."""
import json
import os
import selectors
import subprocess
import time

from harness import CONTROL_LIMIT, INPUT_LIMIT, RequestCancelled, Worker, validate_file_map, validate_paths


class ProbeReader:
    def __init__(self, stream, cancel_event):
        self.stream = stream
        self.cancel_event = cancel_event
        self.deadline = time.monotonic() + 30
        self.pending = bytearray()

    def checkpoint(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RequestCancelled('linked acquisition cancelled')
        if time.monotonic() >= self.deadline:
            raise TimeoutError('linked acquisition deadline')

    def fill(self):
        self.checkpoint()
        with selectors.DefaultSelector() as selector:
            selector.register(self.stream, selectors.EVENT_READ)
            while not selector.select(.01):
                self.checkpoint()
            data = os.read(self.stream.fileno(), 65536)
        if not data:
            raise RuntimeError('acquisition probe EOF; openat2 and unchanged regular files required')
        self.pending.extend(data)

    def exact(self, size):
        output = bytearray()
        while len(output) < size:
            self.checkpoint()
            if not self.pending:
                self.fill()
            count = min(size - len(output), len(self.pending))
            output.extend(self.pending[:count])
            del self.pending[:count]
        return bytes(output)

    def line(self):
        while b'\n' not in self.pending:
            if len(self.pending) > CONTROL_LIMIT:
                raise ValueError('probe control limit')
            self.fill()
        end = self.pending.index(b'\n') + 1
        if end > CONTROL_LIMIT:
            raise ValueError('probe control limit')
        line = bytes(self.pending[:end])
        del self.pending[:end]
        return line


def acquire(build, base_fd, main_fd, main_name, *, trace=None, evidence=None,
            cancel_event=None, diagnostic=None):
    """Caller keeps descriptor ownership. Return a complete immutable byte map or raise.

    main_name is relative to the pinned base and must identify the supplied main fd.
    Discovery receives bytes only; it has no original-directory descriptor or mount.
    """
    evidence = evidence if evidence is not None else {}
    process = subprocess.Popen([str(build / 'linked-probe'), str(base_fd), str(main_fd), main_name],
                               pass_fds=(base_fd, main_fd), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    worker = None
    try:
        reader = ProbeReader(process.stdout, cancel_event)
        size = int(reader.line())
        if not 0 <= size <= 10 * 1024 * 1024:
            raise ValueError('main SVG limit')
        main = reader.exact(size)
        if diagnostic:
            diagnostic('main-captured')
        worker = Worker(build / 'qt-worker', trace=trace)
        response = worker.request('svg-resources', main, cancel_event=cancel_event)
        evidence['discovery'] = response
        if response.get('outcome') != 'resources':
            raise ValueError('SVG resource policy rejected')
        paths = validate_paths(response.get('paths'))
        evidence['paths'] = paths
        worker.close()
        evidence['discovery_cleanup'] = worker.cleanup
        if not worker.scope_empty:
            raise RuntimeError('discovery cleanup unverified')
        if diagnostic:
            diagnostic('manifest-validated')
        reader.checkpoint()
        manifest = json.dumps(dict(paths=paths), ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
        if len(manifest) > CONTROL_LIMIT:
            raise ValueError('manifest control limit')
        # Manifest <= PIPE_BUF is not assumed: bound writes and observe cancellation.
        os.set_blocking(process.stdin.fileno(), False)
        offset = 0
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            while offset < len(manifest):
                reader.checkpoint()
                if selector.select(.01):
                    try:
                        offset += os.write(process.stdin.fileno(), manifest[offset:offset + 4096])
                    except BlockingIOError:
                        pass
        process.stdin.close()
        record = json.loads(reader.line())
        entries = record.get('files')
        if not isinstance(entries, list) or len(entries) != len(paths) + 1:
            raise ValueError('probe file count')
        files = {}
        total = 0
        for entry in entries:
            name, size = entry.get('path'), entry.get('bytes')
            if name not in paths + ['main.svg'] or name in files or type(size) is not int or size < 0:
                raise ValueError('invalid probe entry')
            total += size
            if total > INPUT_LIMIT:
                raise ValueError('aggregate input limit')
            files[name] = reader.exact(size)
        process.wait(timeout=max(.001, reader.deadline - time.monotonic()))
        if process.returncode or reader.pending or process.stdout.read(1):
            raise RuntimeError('probe failed or trailing data')
        validate_file_map(files)
        if files['main.svg'] != main:
            raise ValueError('probe main mismatch')
        evidence['identities'] = entries
        reader.checkpoint()
        if diagnostic:
            diagnostic('before-publication')
        reader.checkpoint()
        return files
    finally:
        try:
            if worker is not None:
                try:
                    worker.close()
                finally:
                    evidence['discovery_cleanup'] = worker.cleanup
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            evidence['probe_status'] = process.returncode
            evidence['probe_stderr'] = process.stderr.read().decode(errors='replace')
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
