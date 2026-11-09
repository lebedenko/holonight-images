#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import sys
import tempfile
import unittest
import run


def samples(base=40_000_000, candidate=36_000_000):
    return [dict(**c, accepted=True, total_ns=base if c['variant'] == 'baseline' else candidate,
                 fd_before=4, fd_after=4) for c in run.schedule()]


class Tests(unittest.TestCase):
    def test_pairing_accounting_and_warmup_exclusion(self):
        rows = samples()
        for row in rows:
            if row['stage'] == 'warmup':
                row['total_ns'] = 1
        report = run.summarize(rows)
        self.assertTrue(all(r['passes'] for r in report['results'].values()))
        self.assertEqual(report['results']['pooled']['pairs'], 150)
        self.assertEqual(report['results']['pooled']['variants']['candidate']['n'], 150)
        for block, first in enumerate(('baseline', 'candidate', 'baseline')):
            self.assertEqual(rows[block * 110]['variant'], first)
        for bad in (rows[:-1], rows + rows[:1], [rows[1], rows[0]] + rows[2:]):
            with self.assertRaises(ValueError):
                run.summarize(bad)

    def test_threshold_boundaries(self):
        for base, candidate, passed in ((40_000_000, 36_000_000, True),
                (40_000_000, 36_000_001, False), (50_000_000, 46_000_000, False),
                (30_000_000, 27_000_000, False)):
            self.assertEqual(run.summarize(samples(base, candidate))['results']['pooled']['passes'], passed)

    def test_inconsistent_block(self):
        rows = samples(50_000_000, 35_000_000)
        for row in rows:
            if row['block'] == 1 and row['variant'] == 'candidate':
                row['total_ns'] = 49_000_000
        report = run.summarize(rows)
        self.assertTrue(report['results']['pooled']['passes'])
        self.assertEqual(report['decision'], 'worthwhile savings not demonstrated')

    def test_p95_regression_and_nearest_rank(self):
        for tail, passed in ((42_000_000, True), (42_000_001, False)):
            rows = samples()
            for row in rows:
                if row['variant'] == 'candidate' and row['pair'] >= 52:
                    row['total_ns'] = tail
            result = run.summarize(rows)['results']['0']
            self.assertEqual(result['variants']['candidate']['p95'], tail)
            self.assertEqual(result['passes'], passed)

    def test_strict_output(self):
        good = dict(accepted=True, total_ns=1, fd_before=4, fd_after=4)
        for bad in ('{}', '{', json.dumps(good) + '{}',
                    json.dumps(good).replace('"accepted": true', '"accepted": true, "accepted": true')):
            with self.assertRaises(ValueError):
                run.parse(bad, True)
        for key, value in (('accepted', False), ('total_ns', 0), ('total_ns', -1),
                           ('total_ns', True), ('fd_after', 5)):
            with self.assertRaises(ValueError):
                run.parse(json.dumps(dict(good, **{key: value})), True)

    def test_timeout_retains_partial_and_reaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / 'child'
            h = run.Harness([sys.executable, '-u', '-c',
                "import sys,time,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); sys.stdin.readline(); print('{',end='',flush=True); time.sleep(30)"], prefix, seconds=.2)
            try:
                with self.assertRaises(TimeoutError):
                    h.request('/unused')
            finally:
                result = h.close(True)
            self.assertTrue(result['reaped'] and result['proc_absent'] and result['timeout'])
            self.assertEqual(prefix.with_suffix('.stdout').read_bytes(), b'{')

    def test_idle_lifetime_is_enforced_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = run.Harness([sys.executable, '-c', 'import time; time.sleep(30)'],
                            Path(tmp) / 'idle', seconds=.2)
            try:
                h.process.wait(timeout=3)
                self.assertTrue(h.expired.is_set())
                with self.assertRaises(TimeoutError):
                    h.request('/unused')
            finally:
                result = h.close()
            self.assertTrue(result['reaped'] and result['proc_absent'])

    def test_trailing_output_and_process_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            for suffix, script in [('trailing', "sys.stdin.readline(); print('extra',flush=True)"),
                                   ('failure', 'sys.exit(7)')]:
                h = run.Harness([sys.executable, '-u', '-c', 'import sys; ' + script], Path(tmp) / suffix)
                result = h.close()
                self.assertTrue(result['trailing'] if suffix == 'trailing' else result['returncode'] == 7)


if __name__ == '__main__':
    unittest.main()
