#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""GIF diagnostic contract regressions, also runnable with python -O."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from animation import encode, patch
from gif_attribution import expectations, pixels, signature, diagnostic_status
from runtime_evidence import Invocation, validate_report

spec=importlib.util.spec_from_file_location('triage',Path(__file__).with_name('animation-triage.py'))
triage=importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)


class AttributionTests(unittest.TestCase):
    def test_corrupt_fixture_is_rejected(self):
        frames=[patch(0,0,2,1)]
        data=encode(2,1,frames)
        triage.validate(data,2,1,frames,None)
        for corrupted in (b'GIF87a'+data[6:],data[:-1],data+b'x'):
            with self.subTest(data=corrupted):
                with self.assertRaises((ValueError,IndexError)):
                    triage.validate(corrupted,2,1,frames,None)

    def test_oracle_corruption_is_rejected(self):
        original=triage.reference
        try:
            triage.reference=lambda *args: iter([b'wrong'])
            with self.assertRaises(ValueError):
                triage.self_checks()
        finally:
            triage.reference=original

    def test_pixel_lengths_cannot_be_truncated_by_zip(self):
        for a,b in ((b'ab',b'a'),(b'a',b'ab')):
            with self.assertRaises(ValueError): pixels(a,b)

    def test_end_normalization_does_not_hide_failures(self):
        a=[dict(op='frame',response=dict(outcome='end'))]
        b=[dict(op='frame',response=dict(outcome='end',width=0,height=0,delay_ms=99))]
        self.assertEqual(signature(a),signature(b))
        for response in (dict(outcome='failure',error='decoder error'),dict(outcome='end',width=3)):
            with self.assertRaises(ValueError): signature([dict(op='frame',response=response)])

    def test_failed_qualification_can_complete_diagnosis(self):
        findings=[dict(complete=True,qualification='failed')]
        self.assertEqual(diagnostic_status(findings,True,True),dict(status='passed',candidate_qualification='failed'))
        for equivalent,source in ((False,True),(True,False)):
            with self.assertRaises(ValueError): diagnostic_status(findings,equivalent,source)
        with self.assertRaises(ValueError): diagnostic_status([dict(complete=False)],True,True)

    def test_required_artifacts_and_scopes_are_not_optional(self):
        names,needed=expectations()
        self.assertEqual(len(names),79)
        self.assertEqual(sum(n['min_scopes'] for n in needed.values()),144)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            invocation=Invocation(root,'gif-attribution',{},names,needed)
            records=[dict(name=n,status='passed') for n in names]
            self.assertFalse(invocation.finish(records))
            self.assertEqual(invocation.report['status'],'failed')
            # Even replacing the inventory cannot bypass caller-owned requirements.
            report=copy.deepcopy(invocation.report)
            report['status']='passed'
            for record in report['records']: record['status']='passed'
            with self.assertRaises(ValueError):
                validate_report(root,report,names,requirements=needed)

    def test_complete_artifact_inventory_still_requires_created_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'input.gif').write_bytes(b'fixture')
            needed={'probe':dict(artifacts=['input.gif'],min_scopes=1,scopes=[])}
            invocation=Invocation(root,'scope-regression',{},['probe'],needed)
            self.assertFalse(invocation.finish([dict(name='probe',status='passed')]))
            self.assertIn('missing required scope',invocation.report['validation_error'])


if __name__=='__main__':
    unittest.main()
