#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Focused comparison checks. Output is evidence, never an aggregate qualification."""
import argparse
import hashlib
import shutil
import io
import json
import socket
import struct
import zlib
from pathlib import Path
import tempfile

from runtime_evidence import guarded_main, Invocation, destination as evidence_destination, require
from runtime_suites import scenarios, requirements

from harness import Worker, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("--filter", default="")
    parser.add_argument('--evidence-dir', type=Path)
    parser.add_argument('--runtime-bundle', type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    corpus = build / "corpus"
    root = evidence_destination(args, build, 'check-')
    options = dict(filter=args.filter)
    options.update(build=str(build), runtime_bundle=str((args.runtime_bundle or build / 'runtime-bundle').resolve()),
                   evidence_dir=str(root))
    invocation = Invocation(root, 'check', options, scenarios('check', options), requirements('check', options))
    invocation.runtime_bundle = args.runtime_bundle
    checks = []

    def check(name, action):
        if args.filter not in name:
            return
        invocation.scenario(name)
        try:
            detail = action()
            checks.append(dict(name=name, status="passed", detail=detail))
        except (AssertionError, ValueError, OSError, RuntimeError, TimeoutError) as error:
            checks.append(dict(name=name, status="failed", error=str(error)))
        invocation.report["records"] = checks
        invocation.checkpoint()

    def snapshots():
        device = io.BytesIO(b"abcd")
        device.seek(3)
        require(snapshot(device, 4) == b"abcd", 'acceptance check failed: snapshot(device, 4) == b"abcd"')
        require(not device.closed, 'acceptance check failed: not device.closed')
        try:
            snapshot(device, 3)
        except ValueError:
            pass
        else:
            raise AssertionError("oversize accepted")
        class BadSeek(io.BytesIO):
            def seek(self, *args):
                raise OSError("seek fault")
        try:
            snapshot(BadSeek(b"abc"))
        except OSError:
            pass
        else:
            raise AssertionError("seek fault accepted")
        class Underreported(io.BytesIO):
            def size(self):
                return 0
        try:
            snapshot(Underreported(b"abcde"), 4)
        except ValueError:
            pass
        else:
            raise AssertionError("underreported source accepted")
        class ReadFault(io.BytesIO):
            def read(self, *args):
                return None
        try:
            snapshot(ReadFault(b"abc"))
        except OSError:
            pass
        else:
            raise AssertionError("read fault accepted")
        return "offset zero, actual limit, ownership, underreported size and read/seek faults"
    check("snapshot", snapshots)

    def faults(mode):
        worker = Worker(build / "fault-worker", arguments=[mode])
        try:
            try:
                worker.request("load")
            except (OSError, RuntimeError, ValueError, TimeoutError):
                pass
            else:
                raise AssertionError("hostile response accepted")
        finally:
            worker.close()
        require(worker.process.poll() is not None, 'acceptance check failed: worker.process.poll() is not None')
        require(worker.scope_empty, "scope cleanup unverified")
        if worker.cgroup and worker.cgroup.exists():
            require(not (worker.cgroup / "cgroup.procs").read_text().strip(), "orphan processes")
        return "explicit failure; scope empty or removed"
    for mode in ("crash", "control", "oversize", "stride", "hang"):
        check("protocol-" + mode, lambda mode=mode: faults(mode))

    def probe():
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            worker = Worker(build / "fault-worker", arguments=["probe", corpus / "alpha.png", server.getsockname()[1]],
                            trace=build / "negative-probe.trace")
            try:
                result = worker.request("probe")
                require(result["original_readable"] is False, result)
                require(result["host_network_reachable"] is False, result)
                return result
            finally:
                worker.abort()
                worker.close()
    check("filesystem-network-isolation", probe)

    def png(chunks, depth=8, pixels=b"\xc8\x64\x32\x80"):
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
        data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, depth, 6, 0, 0, 0))
        return data + b"".join(chunk(kind, payload) for kind, payload in chunks) + chunk(b"IDAT", zlib.compress(b"\0" + pixels)) + chunk(b"IEND", b"")

    (corpus / "invalid-icc.png").write_bytes(png([(b"iCCP", b"invalid\0\0" + zlib.compress(b"not an ICC profile"))]))
    (corpus / "rgba16.png").write_bytes(png([], 16, bytes.fromhex("c8c8646432328080")))

    for backend in ("qt", "glycin"):
        def color(name, backend=backend):
            worker = Worker(build / (backend + "-worker"), glycin=backend == "glycin",
                            trace=build / (backend + "-sandbox.trace"))
            try:
                worker.request("load", (corpus / name).read_bytes())
                result = worker.request("decode", width=1, height=1)
                if name == "invalid-icc.png":
                    require(result["outcome"] in (0, "success"), result)
                    require(result["first_pixel"] == [100, 50, 25, 128], result)
                    result["uncertainty"] = "Malformed profile fallback; rejection diagnostic unknown"
                else:
                    require(result["first_pixel"] == [100, 50, 25, 128], result)
                return result
            finally:
                worker.close()
        for name in ("rgba16.png", "invalid-icc.png"):
            check(backend + "-color-" + name, lambda name=name: color(name))
        def metadata(backend=backend):
            worker = Worker(build / (backend + "-worker"), glycin=backend == "glycin")
            try:
                loaded = worker.request("load", (corpus / "exif.jpg").read_bytes())
                result = loaded.get("exif") if backend == "glycin" else worker.request("metadata").get("metadata")
                expected = dict(make="SONY", model="ILCE-7M4", lens="FE 24-70mm F2.8 GM II",
                                aperture=8, exposure_seconds=.01, focal_length_mm=32, iso=100,
                                latitude=50.45, longitude=-30.52, altitude_meters=179)
                require(result, loaded)
                for key, value in expected.items():
                    if isinstance(value, str):
                        require(result[key] == value, (key, result))
                    else:
                        require(abs(result[key] - value) < 1e-6, (key, result))
                return result
            finally:
                worker.close()
        check(backend + "-structured-exif", metadata)

        def gif(backend=backend):
            worker = Worker(build / (backend + "-worker"), glycin=backend == "glycin")
            try:
                loaded = worker.request("load", (corpus / "animation.gif").read_bytes())
                sequence = worker.request("gif-open") if backend == "qt" else loaded
                frames = [worker.request("frame") for _ in range(3)]
                delays = [f.get("delay_ms", f.get("delay_us", 0) / 1000) for f in frames[:2]]
                require(delays == [30, 70], frames)
                require(frames[0]["pixel_sha256"] != frames[1]["pixel_sha256"], frames)
                worker.request("restart")
                require(worker.request("frame")["pixel_sha256"] == frames[0]["pixel_sha256"], 'acceptance check failed: worker.request("frame")["pixel_sha256"] == frames[0]["pixel_sha256"]')
                return dict(sequence=sequence, frames=frames)
            finally:
                worker.close()
        check(backend + "-gif-delays-pixels-restart", gif)

        for name, href, accepted in (("same-directory", "image.png", True),
                                     ("descendant", "child/image.png", True),
                                     ("traversal", "../image.png", False),
                                     ("absolute", "/capsule/image.png", False),
                                     ("file-url", "file:///capsule/image.png", False),
                                     ("network", "https://example.invalid/image.png", False),
                                     ("symlink", "escape.png", False),
                                     ("external-xml", "image.png", False)):
            def capsule(backend=backend, href=href, accepted=accepted):
                with tempfile.TemporaryDirectory(dir=build) as directory:
                    root = Path(directory)
                    (root / "child").mkdir()
                    image = (corpus / "alpha.png").read_bytes()
                    (root / "image.png").write_bytes(image)
                    (root / "child/image.png").write_bytes(image)
                    (root / "escape.png").symlink_to("image.png")
                    data = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="64" height="32">'
                            f'<image width="64" height="32" xlink:href="{href}"/></svg>').encode()
                    if name == "external-xml":
                        data = b'<!DOCTYPE svg SYSTEM "file:///etc/passwd">' + data
                    (root / "main.svg").write_bytes(data)
                    worker = Worker(build / (backend + "-worker"), glycin=backend == "glycin", capsule=root)
                    try:
                        # Acquisition already captured a private capsule. Replace every original.
                        (root / "main.svg").write_bytes(b"replaced main")
                        (root / "image.png").write_bytes(b"replaced resource")
                        (root / "child/image.png").write_bytes(b"replaced descendant")
                        loaded = worker.request("load", data, capsule=True)
                        result = worker.request("svg", capsule=True, width=64, height=32)
                        rendered = bool(result["first_pixel"] and result["first_pixel"][3])
                        require(rendered == accepted, dict(loaded=loaded, result=result))
                        if not accepted:
                            require(result["outcome"] != "success", result)
                        return result
                    finally:
                        worker.close()
            check(backend + "-capsule-" + name, capsule)

    destination = build / "checks.json"
    if args.filter and destination.exists():
        previous = json.loads(destination.read_text())
        checked_names = {c["name"] for c in checks}
        previous = [c for c in previous if c["name"] not in checked_names]
    else:
        previous = []
    if destination.exists():
        shutil.copy2(destination, destination.with_name("checks-" + hashlib.sha256(destination.read_bytes()).hexdigest()[:12] + ".json"))
    destination.write_text(json.dumps(previous + checks, indent=2) + "\n")
    for result in checks:
        print(json.dumps(result))
    return 0 if invocation.finish(checks) else 1


if __name__ == "__main__":
    raise SystemExit(guarded_main(main))
