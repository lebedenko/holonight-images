#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the standalone feasibility corpus; retain raw observations, including failures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error("samples must be between 1 and 100")
    build = args.build.resolve()
    binary = build / "glycin-probe"
    corpus = build / "corpus"
    subprocess.run([binary, "fixtures", corpus], check=True, timeout=10)
    # Independent two-frame GIF, 30/70 ms, finite repeat field=1.
    (corpus / "animation.gif").write_bytes(bytes.fromhex(
        "47494638396101000100800000000000ffffff21ff0b") + b"NETSCAPE2.0" + bytes.fromhex(
        "030101000021f90401030000002c0000000001000100000202440100"
        "21f90401070000002c00000000010001000002024c01003b"))
    escape = corpus / "links/escape.png"
    if not escape.is_symlink() and not escape.exists():
        escape.symlink_to("../alpha.png")
    elif not escape.is_symlink() or os.readlink(escape) != "../alpha.png":
        raise RuntimeError(f"Unexpected pre-existing fixture: {escape}")
    observations = []
    cases = [(mode, name) for mode in ("qt", "bytes", "stream")
             for name in ("alpha.png", "large.png", "plain.jpg", "plain.bmp",
                          "exif.jpg", "orientation.jpg", "static.svg", "embedded.svg", "animation.gif")]
    cases += [(mode, f"links/{name}.svg") for mode in ("stream", "path")
              for name in ("local", "parent", "symlink")]
    cases += [("ignore", "orientation.jpg"), ("cancel", "large.png"),
              ("cancel-running", "large.png"), ("frames", "animation.gif")]
    for mode, name in cases:
        for sample in range(args.samples):
            command = [str(binary), mode, str(corpus / name)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                record = json.loads(result.stdout)
                record.update(returncode=result.returncode, stderr=result.stderr)
            except subprocess.TimeoutExpired:
                record = {"ok": False, "error": "15 second probe timeout"}
            record.update(mode=mode, fixture=name, sample=sample)
            observations.append(record)
    summary = []
    for mode, name in cases:
        rows = [r for r in observations if r["mode"] == mode and r["fixture"] == name]
        times = sorted(r["elapsed_us"] for r in rows if r.get("ok"))
        summary.append({"mode": mode, "fixture": name,
                        "successes": sum(bool(r.get("ok")) for r in rows),
                        "median_us": statistics.median(times) if times else None,
                        "max_us": max(times) if times else None})
    report = {
        "host": platform.platform(),
        "glycin": subprocess.check_output(["pkg-config", "--modversion", "glycin-2"], text=True).strip(),
        "qt": subprocess.check_output(["pkg-config", "--modversion", "Qt6Gui"], text=True).strip(),
        "coldness": "Fresh application and loader per sample; OS disk cache uncontrolled; sequential concurrency=1",
        "samples": args.samples,
        "overrides_present": [key for key in ("GLYCIN_DISABLE_SANDBOX", "GLYCIN_DATA_DIR",
                               "XDG_DATA_DIRS", "XDG_DATA_HOME") if key in os.environ],
        "sha256": {str(p.relative_to(corpus)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(corpus.rglob("*")) if p.is_file() and not p.is_symlink()},
        "summary": summary, "observations": observations,
    }
    destination = build / "report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(destination)
    for row in summary:
        print(json.dumps(row))
    # This is an experiment, not an acceptance gate. Unsuccessful decoding is data.


if __name__ == "__main__":
    main()
