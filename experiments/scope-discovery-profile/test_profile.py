#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
from collections import Counter
from pathlib import Path
import copy
import subprocess
import tempfile
import unittest
import accounting as a
import overlay
import run

HERE=Path(__file__).resolve().parent


def events(censored=False, observed=True):
    rows=[('clock_resolution',1,1),('P0',10,0),('P1',20,0)]
    if observed:
        if not censored:
            rows += [('D0',21,0),('classification',25,0),('D1',30,0),('V0',31,0),('V1',40,0)]
        rows += [('D0',41,0),('classification',45,1),('D1',50,1)]
    rows += [('S',52,0),('L',60,0),('P2',100,0),('exit',120,0)]
    return [dict(mark=m,ns=n,value=v,seq=i,pid=123,role='parent') for i,(m,n,v) in enumerate(rows)]


def intervals(censored=False, observed=True):
    return a.intervals(events(censored,observed),observed,1 if censored else 2,0 if censored else 1)


def samples():
    return [dict(s,qualified=True,intervals=intervals(observed=s['variant']=='observed')) for s in a.schedule()]


class Tests(unittest.TestCase):
    def test_conservative_bracket_and_closure(self):
        x=intervals()
        self.assertEqual((x['membership_lower'],x['membership_upper']),(11,40))
        self.assertEqual((x['lag_lower'],x['lag_upper']),(2,31))
        self.assertEqual(x['uncertainty'],29)
        self.assertEqual(x['query_ns'],18)
        self.assertEqual(x['wait_ns'],9)
        self.assertEqual(x['residual_ns'],15)
        self.assertEqual(x['closure_ns'],0)

    def test_first_read_censoring(self):
        x=intervals(True)
        self.assertTrue(x['censored'])
        self.assertEqual((x['membership_lower'],x['membership_upper']),(0,40))
        self.assertEqual((x['lag_lower'],x['lag_upper']),(2,42))

    def test_unknown_and_decision_disagreement_rejected(self):
        with self.assertRaises(ValueError): a.intervals(events(),True,2,1,1)
        for value in (-1,1):
            e=events();e[4]['value']=value
            with self.assertRaises(ValueError): a.intervals(e,True,2,1)
        e=events();e[5]['value']=1
        with self.assertRaises(ValueError): a.intervals(e,True,2,1)

    def test_missing_duplicate_and_unordered_records(self):
        for index in range(len(events())):
            e=events();e.pop(index)
            with self.subTest(index=index),self.assertRaises(ValueError): a.intervals(e,True,2,1)
        for index in range(len(events())):
            e=events();e.insert(index,copy.deepcopy(e[index]))
            with self.assertRaises(ValueError): a.intervals(e,True,2,1)
        e=events();e[4]['ns']=31
        with self.assertRaises(ValueError): a.intervals(e,True,2,1)
        with self.assertRaises(ValueError): a.intervals(events(),False,2,1)
        with self.assertRaises(ValueError): a.intervals(events(),True,3,1)

    def test_schedule_counts_and_pair_orders(self):
        slots=a.schedule()
        self.assertEqual(len(slots),138)
        self.assertEqual(len(a.qualification()),12)
        self.assertEqual(Counter((s['variant'],s['warmup']) for s in slots),
                         {('control',True):9,('observed',True):9,('control',False):60,('observed',False):60})
        for i in range(0,len(slots),2):
            self.assertEqual(slots[i]['pair'],slots[i+1]['pair'])
            self.assertEqual(slots[i]['variant'],'control' if i//2%2==0 else 'observed')
        for block in range(3):
            self.assertEqual(Counter(s['order'] for s in slots if s['block']==block and not s['warmup'] and s['variant']=='control'),
                             {'control-first':10,'observed-first':10})

    def test_stats_threshold_equality_and_failure(self):
        self.assertEqual(a.stats(list(range(1,21))),dict(n=20,median=10.5,p95=19,maximum=20))
        self.assertTrue(a.ratio([100]*20,[110]*20)['passed'])
        self.assertFalse(a.ratio([100]*20,[111]*20)['passed'])
        self.assertFalse(a.ratio([100]*20,[100]*18+[111]*2)['passed'])
        self.assertFalse(a.ratio([0],[0])['passed'])

    def test_warmups_excluded_censoring_retained(self):
        data=samples()
        for s in data:
            if s['warmup']: s['intervals']['outer']=1000000
            if s['variant']=='observed' and s['pair']%2: s['intervals']=intervals(True)
        r=a.summary(a.schedule(),data,True)
        self.assertEqual(r['verdict'],a.VERDICT)
        pooled=r['rows'][-1]
        self.assertEqual(pooled['variants']['control']['outer']['median'],90)
        self.assertEqual(pooled['censoring']['all']['n'],60)
        self.assertEqual(pooled['censoring']['censored']['n'],30)
        self.assertEqual(pooled['censoring']['uncensored']['n'],30)

    def test_each_block_and_both_overhead_metrics_gate(self):
        for metric in ('outer','discovery'):
            data=samples()
            for s in data:
                if s['block']==0 and s['variant']=='observed' and not s['warmup']:
                    s['intervals'][metric]*=1.2
            r=a.summary(a.schedule(),data,True)
            self.assertEqual(r['verdict'],a.FAILURE)
            self.assertTrue(r['rows'][-1]['gates'][metric]['median']<=1.10)

    def test_partial_run_and_qualification_gate(self):
        slots=a.schedule();data=samples()
        self.assertEqual(a.summary(slots,data)['verdict'],a.FAILURE)
        r=a.summary(slots,data[:1],True)
        self.assertEqual(r['attempted'],1)
        self.assertEqual(len(r['unattempted']),137)
        self.assertEqual(r['verdict'],a.FAILURE)
        self.assertEqual(a.summary(slots,data[1:],True)['verdict'],a.FAILURE)
        with self.assertRaises(ValueError): a.summary(slots,data+data[:1],True)

    def test_stale_inventory_and_anchors(self):
        with tempfile.TemporaryDirectory() as d:
            src,dst=Path(d)/'src',Path(d)/'dst';src.mkdir();dst.mkdir()
            (src/'a').write_text('new');(dst/'a').write_text('old')
            run.stage_tooling(src,dst)
            self.assertEqual(run.inventory(src),run.inventory(dst))
            (dst/'extra').touch()
            with self.assertRaises(ValueError):run.stage_tooling(src,dst)
        with self.assertRaises(ValueError):overlay.runtime('stale')
        with self.assertRaises(ValueError):overlay.replace('x x','x','y')

    def test_normal_configuration_and_overlay(self):
        text=(HERE.parents[1]/'src/isolated/runtime.cpp').read_text()
        changed=overlay.runtime(text)
        self.assertIn('if (!Profile::qualification) process.setStandardErrorFile(QProcess::nullDevice());',changed)
        self.assertIn('if (Profile::qualification) sandbox << "--profile"',changed)
        self.assertIn('Profile::fault != "measure" && Profile::fault != "success"',(HERE/'harness.cpp').read_text())
        self.assertIn('childEnabled = qualify;',(HERE/'telemetry.h').read_text())
        helper=overlay.helper((HERE.parents[1]/'src/isolated/helper.cpp').read_text())
        self.assertIn('if (qualify) Profile::childStart(gate, true, Profile::now());',helper)
        self.assertNotIn('clock_getres',helper)

    def test_descendant_regression(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'fault'
            subprocess.run(['c++','-std=c++23','-Wall','-Wextra','-Werror',str(HERE/'test_fault_control.cpp'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_cpp_classification_and_production_decision(self):
        original=(HERE.parents[1]/'src/isolated/runtime.cpp').read_text()
        changed=overlay.runtime(original)
        def group(text):return text[text.index('QString groupOf('):text.index('class NativeCleanup')]
        read=changed[changed.index('QByteArray fileBytes('):changed.index('QProcessEnvironment environment()')]
        source='''#define PROFILE_DETAILED 1
#include "telemetry.h"
#include <QTemporaryFile>
#include <cassert>
QByteArray input;
bool readOK=true;
namespace Original {
QByteArray fileBytes(const QString&) { return input; }
'''+group(original)+'''}
namespace Observed {
QByteArray fileBytes(const QString&) { Profile::readValid=readOK; return input; }
'''+group(changed)+'''}
namespace Read {
constexpr qint64 controlCeiling=64;
'''+read+'''}
int main() {
 const QString unit="target.scope";
 struct Case { QByteArray data; int expected; };
 const Case cases[]={{"0::/old\\n",0},{"0::/target.scope\\n",1},{"",-1},
 {"0::/target.scope",-1},{"0::/target.scope\\n0::/old\\n",-1},
 {"1:cpu:/old\\n",-1},{"0::/old/../target.scope\\n",-1},
 {"0::/prefix-target.scope\\n",-1},{"0::/target.scope (deleted)\\n",-1},
 {QByteArray("0::/x\\0y\\n",8),-1},{"0::/target.scope\\r\\n",-1}};
 for (const auto& c:cases) {
   input=c.data;
   assert(Profile::classify(input,unit,true)==c.expected);
   for (bool ok:{true,false}) {
     readOK=ok;
     assert(Original::groupOf(123,unit)==Observed::groupOf(123,unit));
   }
   assert(Profile::classify(input,unit,false)==-1);
 }
 QTemporaryFile file; assert(file.open());
 for (const QByteArray& bytes:{QByteArray("0::/old\\n"),QByteArray("0::/old"),QByteArray(65,'x')}) {
   file.resize(0);file.seek(0);file.write(bytes);file.flush();
   Profile::reading=true;
   const auto returned=Read::fileBytes(file.fileName());
   assert(returned==(bytes.size()<=64?bytes:QByteArray{}));
   assert(Profile::readValid==(bytes.size()<64 && bytes.endsWith('\\n')));
 }
 assert(Read::fileBytes(file.fileName()+"-missing").isEmpty());
 assert(!Profile::readValid);
 Profile::used=Profile::recordLimit;
 Profile::mark("D0");assert(Profile::failed);
}
'''
        with tempfile.TemporaryDirectory() as d:
            cpp,exe=Path(d)/'test.cpp',Path(d)/'test';cpp.write_text(source)
            flags=subprocess.check_output(['pkg-config','--cflags','--libs','Qt6Core'],text=True).split()
            subprocess.run(['c++','-std=c++23','-Wall','-Wextra','-Werror','-I'+str(HERE),str(cpp),'-o',str(exe)]+flags,check=True)
            subprocess.run([str(exe)],check=True)


if __name__=='__main__': unittest.main()
