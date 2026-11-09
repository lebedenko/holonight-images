# SPDX-License-Identifier: GPL-3.0-or-later
"""Conservative parent-only bounds; nanoseconds throughout."""
import statistics
from legacy_accounting import parse, validate_sequences, ratio, LIMIT, BYTE_LIMIT, CASES

VARIANTS = ('control', 'observed')
VERDICT = 'qualified interval bounds under the stated assumptions'
FAILURE = 'no qualified scope-discovery attribution'


def schedule():
    slots = []
    for pair in range(69):
        order = VARIANTS if pair % 2 == 0 else VARIANTS[::-1]
        for variant in order:
            slots.append(dict(id=f'm{len(slots):03}', phase='measurement', block=pair//23,
                              pair=pair, order=order[0]+'-first', warmup=pair%23 < 3,
                              kind='inspection', variant=variant, case='measure'))
    return slots


def qualification():
    return [dict(id=f'q{i:02}', phase='qualification', block=None, pair=None, order=None,
                 warmup=False, kind='inspection', variant=v, case=c)
            for i, (v, c) in enumerate((v, c) for v in VARIANTS for c in CASES)]


def stats(values):
    ordered = sorted(values)
    return dict(n=len(values), median=statistics.median(values) if values else None,
                p95=ordered[(95*len(values)+99)//100-1] if values else None,
                maximum=max(values) if values else None)


def intervals(events, observed, queries=None, waits=None, unknown=0, readiness=True):
    if not events or len(events) > LIMIT or unknown:
        raise ValueError('missing/overflow/unknown observation')
    if any(e['role'] != 'parent' or any(type(e[k]) is not int for k in ('ns','seq','pid','value')) for e in events):
        raise ValueError('parent integer records required')
    validate_sequences(events)
    common = ('clock_resolution', 'P0', 'P1', 'S', 'L', 'P2', 'exit')
    if not readiness:
        common = tuple(k for k in common if k != 'P2')
    marks = {}
    for e in events:
        if e['mark'] in common:
            if e['mark'] in marks:
                raise ValueError('duplicate boundary')
            marks[e['mark']] = e
        elif e['mark'] not in ('D0','classification','D1','V0','V1'):
            raise ValueError('unknown parent mark')
    if any(k not in marks for k in common):
        raise ValueError('missing boundary')
    if [marks[k]['seq'] for k in common] != sorted(marks[k]['seq'] for k in common):
        raise ValueError('boundary order')
    if marks['clock_resolution']['value'] <= 0 or marks['exit']['value'] != 0:
        raise ValueError('clock/reaping')
    p0, p1, s, l, end = [marks[k]['ns'] for k in ('P0','P1','S','L','exit')]
    p2 = marks['P2']['ns'] if readiness else l
    if not p0 <= p1 <= s <= l <= p2 <= end or s == p0 or p2 == p0:
        raise ValueError('boundary chronology')
    if type(queries) is not int or type(waits) is not int or queries < 1 or waits != queries-1:
        raise ValueError('query/wait counts')
    result = dict(outer=p2-p0 if readiness else None, discovery=s-p0, queries=queries, waits=waits,
                  limits=l-s, after_limits=p2-l if readiness else None, exit=end-p0)
    details = [e for e in events if e['mark'] not in common]
    if not observed:
        if details:
            raise ValueError('control contains detailed records')
        return result
    index, reads, spans = 0, [], []
    for query in range(queries):
        expected = ['D0','classification','D1']
        row = details[index:index+3]
        if [e['mark'] for e in row] != expected:
            raise ValueError('missing or unordered query')
        start, classification, stop = row
        match = query == queries-1
        if classification['value'] != int(match) or stop['value'] != int(match):
            raise ValueError('unknown/nonmonotonic/decision mismatch')
        if not p1 <= start['ns'] <= classification['ns'] <= stop['ns'] <= s:
            raise ValueError('read outside discovery')
        reads.append((start['ns'],stop['ns']))
        index += 3
        if not match:
            row = details[index:index+2]
            if [e['mark'] for e in row] != ['V0','V1'] or row[1]['value'] not in (0,1):
                raise ValueError('missing wait')
            if not stop['ns'] <= row[0]['ns'] <= row[1]['ns'] <= s:
                raise ValueError('wait order')
            spans.append((row[0]['ns'],row[1]['ns']))
            index += 2
    if index != len(details) or marks['S']['seq'] != details[-1]['seq']+1:
        raise ValueError('extra records or missing discovery boundary')
    lower = reads[-2][0] if len(reads)>1 else p0
    upper = reads[-1][1]
    query_ns = sum(y-x for x,y in reads)
    wait_ns = sum(y-x for x,y in spans)
    residual = s-p0-query_ns-wait_ns
    if residual < 0:
        raise ValueError('negative residual')
    result.update(censored=len(reads)==1, membership_lower=lower-p0, membership_upper=upper-p0,
                  lag_lower=s-upper, lag_upper=s-lower, uncertainty=upper-lower,
                  query_ns=query_ns, wait_ns=wait_ns, residual_ns=residual,
                  closure_ns=(s-p0)-(query_ns+wait_ns+residual))
    if result['membership_lower']+result['lag_upper'] != result['discovery'] or result['membership_upper']+result['lag_lower'] != result['discovery']:
        raise ValueError('bound closure')
    return result


def summary(slots, samples, qualification_passed=False):
    planned = {s['id']: s for s in slots}
    seen = set()
    for sample in samples:
        if sample['id'] in seen or sample['id'] not in planned or any(sample[k]!=v for k,v in planned[sample['id']].items()):
            raise ValueError('duplicate/foreign/misassociated sample')
        seen.add(sample['id'])
    rows = []
    all_gates = True
    for block in (0,1,2,None):
        selected = [s for s in samples if (block is None or s['block']==block) and not s['warmup'] and s['qualified']]
        row = dict(block=block, variants={}, gates={}, pairs={}, pair_deltas=[], censoring={})
        for variant in VARIANTS:
            group = [s['intervals'] for s in selected if s['variant']==variant]
            keys = sorted({k for x in group for k in x if k != 'censored'})
            row['variants'][variant] = {k:stats([x[k] for x in group]) for k in keys}
        for key in ('outer','discovery'):
            gate = ratio(*[[s['intervals'][key] for s in selected if s['variant']==v] for v in VARIANTS])
            row['gates'][key] = gate
            all_gates &= gate['passed']
        for label,censor in [('all',None),('censored',True),('uncensored',False)]:
            group = [s['intervals'] for s in selected if s['variant']=='observed' and (censor is None or s['intervals']['censored']==censor)]
            row['censoring'][label] = dict(n=len(group), **{k:stats([x[k] for x in group]) for k in ('membership_lower','membership_upper','lag_lower','lag_upper','uncertainty')})
        for order in ('control-first','observed-first'):
            pairs = {}
            for sample in selected:
                if sample['order']==order:
                    pairs.setdefault(sample['pair'],{})[sample['variant']]=sample['intervals']
            complete = [p for p in pairs.values() if set(p)==set(VARIANTS)]
            row['pair_deltas'].extend(dict(pair=pair,order=order,**{key:p['observed'][key]-p['control'][key] for key in ('outer','discovery')}) for pair,p in pairs.items() if set(p)==set(VARIANTS))
            row['pairs'][order] = {key:stats([p['observed'][key]-p['control'][key] for p in complete]) for key in ('outer','discovery')}
        rows.append(row)
    complete = len(seen)==len(slots) and all(s['qualified'] for s in samples)
    return dict(version=1, verdict=VERDICT if qualification_passed and complete and all_gates else FAILURE,
                complete=complete, overhead_passed=all_gates, attempted=len(samples),
                unattempted=[s for s in slots if s['id'] not in seen], rows=rows,
                descriptive_pairs=True, qualification_passed=qualification_passed)
