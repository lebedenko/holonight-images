#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import copy
from collections import Counter
import unittest
import subprocess
import tempfile
from pathlib import Path

import accounting as a
import overlay
import run


def observations():
    parent = [('clock_inode',1,42),('clock_resolution',2,1),('clock_sec',3,0),('clock_nsec',4,0),
              ('P0',10,0),('P1',20,0),('D0',21,0),('D1',22,0),('V0',23,0),('V1',30,0),
              ('D0',31,0),('D1',40,1),('S',40,0),('L',50,0),('W0',51,0),('W1',61,1),
              ('W2',62,0),('W3',63,1),('Q0',64,0),('Q1',90,1),('P2',100,0),('exit',130,0)]
    gate = [('clock_inode',25,42),('clock_resolution',26,1),('clock_sec',27,0),('clock_nsec',28,0),('G0',29,0),('G1',60,0),('X',65,0)]
    helper = [('H',70,0),('clock_inode',71,42),('clock_resolution',72,1),('clock_sec',73,0),('clock_nsec',74,0),('R0',80,0),('R1',81,1),('F0',82,0),('F1',110,1),('T',120,0)]
    return [dict(role=role,mark=m,ns=n,value=v,seq=i,pid=pid) for role,pid,items in [('parent',123,parent),('gate',456,gate),('helper',1,helper)] for i,(m,n,v) in enumerate(items)]


def durations(outer=100, leader='S-P0'):
    return dict(outer=outer, **{n: outer*(.5 if n==leader else .1) for n in a.RANKED_INTERVALS})


class AccountingTests(unittest.TestCase):
    def test_complete_schedule_and_continuous_pair_rotation(self):
        schedule=a.schedule()
        self.assertEqual(len(schedule),414)
        self.assertEqual(Counter((s['variant'],s['warmup']) for s in schedule),
                         {('reference',True):27,('detailed',True):27,('reference',False):180,('detailed',False):180})
        for i in range(0,414,2):
            x,y=schedule[i:i+2]
            self.assertEqual(x['pair'],y['pair'])
            self.assertEqual(x['variant'],'reference' if i//2%2==0 else 'detailed')
        self.assertEqual([schedule[b*138]['kind'] for b in range(3)],list(a.KINDS))
        self.assertEqual(len(a.qualification()),36)

    def test_statistics_and_exact_threshold(self):
        self.assertEqual(a.stats([1,2,3,4])['median'],2.5)
        self.assertEqual(a.stats(list(range(1,21)))['p95'],19)
        self.assertTrue(a.ratio([100]*20,[110]*20)['passed'])
        self.assertFalse(a.ratio([100]*20,[110.0001]*20)['passed'])
        self.assertFalse(a.ratio([100]*20,[100]*18+[111]*2)['passed'])
        self.assertFalse(a.ratio([0],[1])['passed'])
        self.assertFalse(a.ratio([],[])['passed'])

    def test_flush_return_after_receipt_and_gate_write_return_after_consumption(self):
        result=a.intervals(observations(),True)
        self.assertEqual(result['outer'],90)
        self.assertEqual(result['gate-parent-overlap'],21)
        self.assertEqual(result['gate-parent-union'],50)
        self.assertEqual(result['discovery_count'],2)
        self.assertEqual(result['discovery_wait_ns'],7)
        self.assertEqual(result['F1-F0'],28)
        self.assertEqual(sum(result[n] for n in ('S-P0','L-S','G1-L','X-G1','H-X','R0-H','P2-R0')),90)

    def test_missing_duplicate_or_incompatible_records_rejected(self):
        for mark in ('P0','P2','S','L','G1','X','H','R0','F1','T','exit'):
            with self.subTest(mark=mark), self.assertRaises((ValueError,KeyError)):
                a.intervals([e for e in observations() if e['mark']!=mark],True)
        events=observations()
        events.append(copy.deepcopy(events[-1]))
        with self.assertRaises(ValueError): a.intervals(events,True)
        for mark,value in [('clock_inode',99),('clock_nsec',1),('H',49)]:
            events=observations()
            for e in events:
                if e['role']=='helper' and e['mark']==mark:
                    e['ns' if mark=='H' else 'value']=value
            with self.assertRaises(ValueError): a.intervals(events,True)

    def test_wire_is_strict_and_bounded(self):
        valid=b'LRP1 gate 0 123 G0 100 0\n'
        self.assertEqual(a.parse(valid)[0]['pid'],123)
        for bad in (valid[:-1],valid+valid,valid+valid.replace(b'gate 0',b'gate 1'),valid.replace(b'100',b'1'*600),valid.replace(b'LRP1',b'LRP2'),valid.replace(b'G0',b'unknown'),valid.replace(b'G0',b'H'),b'x'*(a.BYTE_LIMIT+1),valid.replace(b' 0 123',b' 1 123')):
            with self.subTest(bad=bad[:60]),self.assertRaises(ValueError): a.parse(bad)
        self.assertEqual(a.parse(b'launcher message\n'+valid),a.parse(valid))

    def test_parent_ledger_cannot_wrap_or_exceed_cap(self):
        event=observations()[0]
        with self.assertRaisesRegex(ValueError,'parent capture'):
            a.intervals([dict(event,seq=i) for i in range(a.LIMIT+1)],True)

    def test_overlap_union(self):
        self.assertEqual(a.union([(1,10),(3,5),(8,15),(20,22)]),16)
        with self.assertRaises(ValueError): a.union([(2,1)])

    def test_warmups_are_excluded_and_failed_block_cannot_hide_in_pool(self):
        slots=a.schedule()
        samples=[dict(s,qualified=True,intervals=durations(1000000 if s['warmup'] else 100)) for s in slots]
        summary=a.summary(slots,samples,qualification_passed=True)
        self.assertEqual(summary['verdict'],'qualified attribution')
        self.assertTrue(all(r['variants']['reference']['intervals']['outer']['median']==100 for r in summary['rows']))
        for s in samples:
            if s['variant']=='detailed' and s['block']==0 and s['kind']=='source' and not s['warmup']:
                s['intervals']=durations(200)
        self.assertEqual(a.summary(slots,samples,qualification_passed=True)['verdict'],'no qualified attribution')

    def test_missing_warmup_is_incomplete_even_with_all_measurements(self):
        slots=a.schedule()
        samples=[dict(s,qualified=True,intervals=durations()) for s in slots if s['id']!='m000']
        self.assertEqual(a.summary(slots,samples,qualification_passed=True)['verdict'],'no qualified attribution')

    def test_partial_run_preserves_slots_and_operation_association(self):
        slots=a.schedule()
        sample=dict(slots[0],qualified=False,error='missing observations')
        summary=a.summary(slots,[sample])
        self.assertEqual(summary['attempted'],1)
        self.assertEqual(len(summary['unattempted']),413)
        self.assertEqual(summary['verdict'],'no qualified attribution')
        self.assertEqual(summary['rows'][0]['variants']['reference']['failures'],1)
        with self.assertRaises(ValueError): a.summary(slots,[sample,sample])

    def test_descendant_cancellation_requires_helper_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory)/'fault-control'
            subprocess.run(['c++','-std=c++23','-Wall','-Wextra','-Werror',
                            str(Path(__file__).with_name('test_fault_control.cpp')),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)


    def test_archive_with_tooling_is_overlaid_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot, archive = Path(directory)/'snapshot', Path(directory)/'archive'
            snapshot.mkdir(); archive.mkdir()
            (snapshot/'run.py').write_text('new')
            (archive/'run.py').write_text('old')
            run.stage_tooling(snapshot, archive)
            self.assertEqual(run.inventory(snapshot), run.inventory(archive))

    def test_stale_archive_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot, archive = Path(directory)/'snapshot', Path(directory)/'archive'
            snapshot.mkdir(); archive.mkdir()
            (archive/'stale.py').write_text('stale')
            with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                run.stage_tooling(snapshot, archive)

    def test_rankings_stable_changing_and_tied(self):
        slots=a.schedule()
        samples=[dict(s,qualified=True,intervals=durations()) for s in slots]
        report=a.summary(slots,samples,True)
        self.assertEqual(report['consistency']['source']['consistent_unique_leader'],'S-P0')
        for sample in samples:
            if sample['kind']=='source' and sample['block']==1:
                sample['intervals']=durations(100,'H-X')
        report=a.summary(slots,samples,True)
        self.assertIsNone(report['consistency']['source']['consistent_unique_leader'])
        tied=dict(outer=100, **dict(zip(a.RANKED_INTERVALS,[30,30,10,10,10,10])))
        result=a.ranking([dict(intervals=tied)])
        self.assertEqual(result['leaders'],['S-P0','L-S'])
        self.assertEqual(result['rows'][0]['largest_count'],1)
        self.assertEqual(result['rows'][0]['unique_largest_count'],0)

    def test_shares_are_computed_per_call_and_closure_is_required(self):
        first=dict(outer=100, **dict(zip(a.RANKED_INTERVALS,[80,4,4,4,4,4])))
        second=dict(outer=1000, **dict(zip(a.RANKED_INTERVALS,[100,180,180,180,180,180])))
        result=a.ranking([dict(intervals=c) for c in (first,second)])
        row=next(r for r in result['rows'] if r['interval']=='S-P0')
        self.assertAlmostEqual(row['median_share'],.45)
        self.assertNotAlmostEqual(row['median_share'],90/550)
        first['outer']=101
        with self.assertRaisesRegex(ValueError,'closure'):
            a.ranking([dict(intervals=first)])

    def test_qualification_gates_ranking_conclusions(self):
        slots=a.schedule()
        samples=[dict(s,qualified=True,intervals=durations()) for s in slots]
        report=a.summary(slots,samples)
        self.assertEqual(report['verdict'],'no qualified attribution')
        self.assertEqual(report['ranking_status'],'descriptive only')
        self.assertEqual(a.summary(slots,samples,True)['ranking_status'],'qualified')

    def test_overlay_refuses_stale_anchors(self):
        with self.assertRaises(ValueError): overlay.replace('old old','old','new')
        with self.assertRaises(ValueError): overlay.runtime('wrong source revision')


if __name__=='__main__':
    unittest.main()
