#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Interleaved native Release experiments; failures remain explicit observations."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import time

from harness import Worker, snapshot


def build_details(build):
    lock = Path(__file__).parent / "rust/Cargo.lock"
    return dict(glycin_rust_crate="3.1.0", loader_protocol=2,
                loader_package=subprocess.check_output(["pacman", "-Q", "glycin"], text=True).strip(),
                rustc=subprocess.check_output(["rustc", "--version"], text=True).strip(),
                compiler=subprocess.check_output(["c++", "--version"], text=True).splitlines()[0],
                cmake_cache=(build / "CMakeCache.txt").read_text(),
                rust_profile="release; default opt-level=3; --locked",
                lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
                binary_sha256={name: hashlib.sha256((build / name).read_bytes()).hexdigest()
                               for name in ("qt-worker", "glycin-worker")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--case", help="Rerun one case, preserving other observations with matching binary hashes")
    args = parser.parse_args()
    if not 0 <= args.warmups <= 10 or not 1 <= args.samples <= 100:
        parser.error("invalid repetition count")
    build = args.build.resolve()
    provider = Path(__file__).resolve().parents[2]
    corpus = build / "corpus"
    corpus.mkdir(exist_ok=True)
    subprocess.run(["python3", str(provider / "tests/format-fixtures.py"), str(corpus)], check=True)
    subprocess.run([str(provider / "build/glycin/glycin-probe"), "fixtures", str(corpus)], check=True)
    (corpus / "animation.gif").write_bytes(bytes.fromhex(
        "47494638396101000100800000000000ffffff21ff0b") + b"NETSCAPE2.0" + bytes.fromhex(
        "030101000021f90401030000002c0000000001000100000202440100"
        "21f90401070000002c00000000010001000002024c01003b"))
    backends = [("provider", "qt-worker", False, False), ("qt-helper", "qt-worker", True, False),
                ("glycin-rust", "glycin-worker", True, True)]
    cases = [("thumbnail-alpha", "alpha.png", "decode", 32, 32),
             ("thumbnail-large", "large.png", "decode", 32, 32),
             ("full", "plain.jpg", "decode", 32768, 32768),
             ("metadata", "exif.jpg", "decode", 32, 32),
             ("tiff", "sample.tif", "decode", 32, 32),
             ("webp", "sample.webp", "decode", 32, 32),
             ("bmp", "plain.bmp", "decode", 32, 32),
             ("svg", "static.svg", "svg", 32, 32),
             ("gif", "animation.gif", "frame", 32, 32)]
    if args.smoke:
        cases = cases[:1]
    if args.case:
        cases = [case for case in cases if case[0] == args.case]
        if not cases:
            parser.error("unknown case")
    observations = []
    for repetition in range(-args.warmups, args.samples):
        for case, name, op, width, height in cases:
            with (corpus / name).open("rb") as device:
                data = snapshot(device)
            # Rotate ordering on each repetition, concurrency always one.
            for backend, executable, isolated, glycin in backends[repetition % 3:] + backends[:repetition % 3]:
                record = dict(backend=backend, case=case, fixture=name, repetition=repetition)
                worker = None
                try:
                    worker = Worker(build / executable, isolated=isolated, glycin=glycin)
                    start = worker.started
                    record["load"] = worker.request("load", data)
                    if op == "frame" and not glycin:
                        record["sequence"] = worker.request("gif-open")
                    record["startup_ms"] = (time.monotonic() - start) * 1000
                    start = time.monotonic()
                    record["result"] = worker.request(op, width=width, height=height)
                    record["first_ms"] = (time.monotonic() - start) * 1000
                    if op == "svg":
                        start = time.monotonic()
                        # Glycin still images are one-shot; explicit reload for a new SVG request.
                        if glycin:
                            worker.request("load", data)
                        record["zoom"] = worker.request(op, width=64, height=64)
                        record["zoom_ms"] = (time.monotonic() - start) * 1000
                    if op == "frame":
                        record["second_frame"] = worker.request("frame")
                        record["end"] = worker.request("frame")
                    record["peak_tree_rss_kib"] = worker.peak_rss_kib
                    record["tree_cpu_us"] = worker.cpu_us
                    record["memory_ceiling_verified"] = worker.cgroup is not None
                    record["transport_bytes"] = worker.copied_bytes
                except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                    record["error"] = str(error)
                finally:
                    if worker:
                        record["stderr"] = worker.close()
                observations.append(record)
                print(json.dumps(record), flush=True)
    summary = []
    for backend, *_ in backends:
        for case, *_ in cases:
            rows = [r for r in observations if r["backend"] == backend and r["case"] == case and r["repetition"] >= 0]
            times = sorted(r["startup_ms"] + r["first_ms"] for r in rows if "first_ms" in r)
            summary.append(dict(backend=backend, case=case, observations=len(rows),
                                responses=len(times), median_ms=statistics.median(times) if times else None,
                                p95_ms=times[math.ceil(.95 * len(times)) - 1] if times else None))
    report = dict(host=platform.platform(), cache="OS disk cache uncontrolled", concurrency=1,
                  warmups=args.warmups, samples=args.samples,
                  method="Fresh processes; transport, sampling and postprocessing included; provider baseline uses identical IPC without bwrap",
                  sha256={str(p.relative_to(corpus)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(corpus.rglob("*")) if p.is_file() and not p.is_symlink()},
                  build=build_details(build),
                  packages=subprocess.check_output(["pacman", "-Q", "glycin", "qt6-base", "qt6-svg", "qt6-imageformats", "bubblewrap", "lcms2", "libexif"], text=True),
                  summary=summary, observations=observations)
    destination = build / ("smoke.json" if args.smoke else "report.json")
    if args.case and destination.exists():
        previous = json.loads(destination.read_text())
        if previous.get("build", {}).get("binary_sha256") != report["build"]["binary_sha256"]:
            raise RuntimeError("binary hashes changed; rerun the complete comparison")
        if previous["samples"] != args.samples or previous["warmups"] != args.warmups:
            raise RuntimeError("repetition counts changed; rerun the complete comparison")
        report["summary"] = [r for r in previous["summary"] if r["case"] != args.case] + summary
        report["observations"] = [r for r in previous["observations"] if r["case"] != args.case] + observations
    destination.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
