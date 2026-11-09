# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict stream validation and per-operation interval accounting (nanoseconds)."""
import math
import re
import statistics

KINDS = ('inspection', 'source', 'cached')
VARIANTS = ('reference', 'detailed')
CASES = ('success', 'before', 'await', 'timeout', 'failed', 'descendant')
LIMIT = 32768
BYTE_LIMIT = 256 * 1024
CLOCK = ('clock_inode', 'clock_resolution', 'clock_sec', 'clock_nsec')
CHILD_MARKS = set(CLOCK) | {'H', 'G0', 'G1', 'X', 'R0', 'R1', 'F0', 'F1', 'T', 'fault', 'descendant'}
PARENT_MARKS = set(CLOCK) | {'P0', 'P1', 'S', 'L', 'W0', 'W1', 'W2', 'W3', 'P2', 'D0', 'D1', 'V0', 'V1', 'Q0', 'Q1', 'exit'}
WIRE = re.compile(rb'LRP1 (gate|helper|descendant) (\d+) (\d+) ([A-Za-z0-9_]+) (\d+) (-?\d+)\n')


def schedule():
    slots = []
    pair = 0
    for block in range(3):
        for kind in KINDS[block:] + KINDS[:block]:
            for local in range(23):
                order = VARIANTS if pair % 2 == 0 else VARIANTS[::-1]
                for variant in order:
                    slots.append(dict(id=f'm{len(slots):03}', block=block, kind=kind,
                                      pair=pair, warmup=local < 3, variant=variant, case='measure'))
                pair += 1
    return slots


def qualification():
    return [dict(id=f'q{i:02}', kind=k, variant=v, case=c, warmup=False, block=None, pair=None)
            for i, (v, k, c) in enumerate((v, k, c) for v in VARIANTS for k in KINDS for c in CASES)]


def parse(raw):
    if len(raw) > BYTE_LIMIT:
        raise ValueError('stderr byte limit')
    result = []
    seen = set()
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b'\n'):
            raise ValueError('truncated stderr')
        if not line.startswith(b'LRP'):
            continue  # Retained raw launcher diagnostics, never treated as observations.
        match = WIRE.fullmatch(line)
        if len(line) > 512 or not match:
            raise ValueError('malformed/version/record-size')
        role, seq, pid, mark, ns, value = match.groups()
        mark = mark.decode()
        if mark not in CHILD_MARKS:
            raise ValueError('unknown mark')
        allowed = {'gate': set(CLOCK)|{'G0','G1','X','T'}, 'helper': set(CLOCK)|{'H','R0','R1','F0','F1','T','fault'}, 'descendant': {'descendant'}}
        identity = (role, mark)
        if identity in seen:
            raise ValueError('duplicate child observation')
        seen.add(identity)
        if mark not in allowed[role.decode()]:
            raise ValueError('mark belongs to another process role')
        result.append(dict(role=role.decode(), seq=int(seq), pid=int(pid), mark=mark, ns=int(ns), value=int(value)))
        if len(result) > LIMIT:
            raise ValueError('child record limit')
    validate_sequences(result)
    return result


def validate_sequences(events):
    roles = {}
    for e in events:
        state = roles.setdefault(e['role'], dict(seq=0, pid=e['pid'], ns=0))
        if e['seq'] != state['seq'] or e['pid'] != state['pid'] or e['ns'] < state['ns']:
            raise ValueError('sequence/pid/clock order')
        state.update(seq=state['seq'] + 1, ns=e['ns'])


def unique(events, role):
    result = {}
    for e in events:
        if e['role'] != role:
            continue
        if e['mark'] in result:
            raise ValueError('duplicate observation: ' + e['mark'])
        result[e['mark']] = e
    return result


def stats(values):
    return dict(n=len(values), median=statistics.median(values) if values else None,
                p95=sorted(values)[math.ceil(.95 * len(values))-1] if values else None)


def ratio(reference, detailed):
    if not reference or not detailed or min(reference) <= 0:
        return dict(median=None, p95=None, passed=False)
    r, d = stats(reference), stats(detailed)
    m, p = d['median']/r['median'], d['p95']/r['p95']
    # Compare products, avoiding rounded display values at the boundary.
    return dict(median=m, p95=p, passed=d['median'] * 10 <= r['median'] * 11 and d['p95'] * 10 <= r['p95'] * 11)


def union(spans):
    end = None
    total = 0
    for a, b in sorted(spans):
        if b < a:
            raise ValueError('negative span')
        total += max(0, b - max(a, end if end is not None else a))
        end = max(b, end if end is not None else b)
    return total


def clocks(parent, gate, helper):
    for key in CLOCK:
        values = [r[key]['value'] for r in (parent, gate, helper)]
        if len(set(values)) != 1:
            raise ValueError('incompatible clocks: ' + key)
    if parent['clock_resolution']['value'] <= 0 or any(parent[k]['value'] for k in ('clock_sec', 'clock_nsec')):
        raise ValueError('clock resolution/offset')
    # Actual cross-process causal brackets, without synthetic offset alignment.
    if not (parent['P0']['ns'] <= gate['G0']['ns'] <= gate['G1']['ns'] <= helper['H']['ns'] <= parent['P2']['ns']):
        raise ValueError('clock causal brackets')


def intervals(events, detailed):
    if len(events) > 2 * LIMIT:
        raise ValueError('record limit')
    parent_events = [e for e in events if e['role'] == 'parent']
    if len(parent_events) > LIMIT or any(e['mark'] not in PARENT_MARKS for e in parent_events):
        raise ValueError('parent capture')
    validate_sequences(parent_events)
    repeating = {'D0', 'D1', 'V0', 'V1', 'Q0', 'Q1'}
    p = unique([e for e in parent_events if e['mark'] not in repeating], 'parent')
    if p['exit']['value'] != 0:
        raise ValueError('stream not complete/launcher not reaped')
    outer = p['P2']['ns'] - p['P0']['ns']
    if outer <= 0:
        raise ValueError('nonpositive outer')
    result = {'outer': outer}
    if not detailed:
        return result
    g, h = unique(events, 'gate'), unique(events, 'helper')
    if [e['mark'] for e in events if e['role']=='gate'][-1:] != ['X'] or [e['mark'] for e in events if e['role']=='helper'][-1:] != ['T']:
        raise ValueError('missing terminal record')
    clocks(p, g, h)
    if g['X']['value'] or h['T']['value'] or h['R1']['value'] != 1 or h['F1']['value'] != 1 or p['W1']['value'] != 1:
        raise ValueError('transport/diagnostic write failure')
    if 'T' in g or 'fault' in h or any(e['role'] == 'descendant' for e in events):
        raise ValueError('unexpected terminal role')
    combined = {**p, **g, **h}
    chain = ('P0', 'S', 'L', 'G1', 'X', 'H', 'R0', 'P2')
    spans = []
    for a, b in zip(chain, chain[1:]):
        x, y = combined[a]['ns'], combined[b]['ns']
        if y < x:
            raise ValueError('causal ordering')
        result[b + '-' + a] = y-x
        spans.append((x, y))
    if union(spans) != outer or sum(b-a for a,b in spans) != outer:
        raise ValueError('coverage closure')
    for a,b in [('P0','P1'), ('P1','S'), ('H','P2'), ('R0','R1'), ('F0','F1'), ('R0','P2'), ('G0','G1'), ('W0','W1'), ('W2','W3')]:
        value = combined[b]['ns'] - combined[a]['ns']
        if value < 0:
            raise ValueError('nested ordering')
        result[b+'-'+a] = value
    if not (p['W0']['ns'] <= g['G1']['ns'] and h['R1']['ns'] <= h['F0']['ns']):
        raise ValueError('gate/readiness ordering')
    # F1 can follow P2; flush is a sibling, never an additive transfer phase.
    a,b = g['G0']['ns'], g['G1']['ns']
    c,d = p['P0']['ns'], p['L']['ns']
    result['gate-parent-overlap'] = max(0, min(b,d)-max(a,c))
    result['gate-parent-union'] = union([(a,b),(c,d)])
    for start, end, label in [('D0','D1','discovery'), ('V0','V1','discovery_wait'), ('Q0','Q1','readiness_wait')]:
        selected = [e for e in parent_events if e['mark'] in (start,end)]
        durations = []
        for i in range(0, len(selected), 2):
            if i+1 == len(selected) or selected[i]['mark'] != start or selected[i+1]['mark'] != end:
                raise ValueError('unpaired wait/discovery')
            durations.append(selected[i+1]['ns'] - selected[i]['ns'])
        result[label+'_count'] = len(durations)
        result[label+'_ns'] = sum(durations)
    attempts = [e for e in parent_events if e['mark'] == 'D1']
    if not attempts or [e['value'] for e in attempts] != [0]*(len(attempts)-1)+[1]:
        raise ValueError('scope discovery results')
    return result


def summary(slots, samples):
    indexed = {s['id']: s for s in samples}
    if len(indexed) != len(samples) or set(indexed) - {s['id'] for s in slots}:
        raise ValueError('duplicate/unknown operation association')
    rows = []
    for kind in KINDS:
        for block in (0,1,2,None):
            row = dict(kind=kind, block=block, variants={})
            distributions = {}
            complete = True
            for variant in VARIANTS:
                planned = [s for s in slots if s['kind']==kind and s['variant']==variant and (block is None or s['block']==block)]
                attempted = [indexed[s['id']] for s in planned if s['id'] in indexed]
                measured = [s for s in attempted if not s['warmup'] and s.get('qualified')]
                values = [s['intervals']['outer'] for s in measured]
                distributions[variant] = values
                complete &= len(attempted) == len(planned) and all(s.get('qualified',False) for s in attempted)
                complete &= len(measured) == len([s for s in planned if not s['warmup']])
                names = sorted({'outer'} | {k for s in measured for k in s['intervals']})
                row['variants'][variant] = dict(expected=len(planned), attempted=len(attempted),
                    unattempted=len(planned)-len(attempted),
                    expected_measured=sum(not s['warmup'] for s in planned),
                    warmups=sum(s['warmup'] for s in attempted), measured=len(measured),
                    missing_measured=sum(not s['warmup'] for s in planned)-len(measured),
                    failures=sum(not s.get('qualified',False) for s in attempted),
                    missing_observations=sum(not s.get('qualified',False) for s in attempted),
                    intervals={k:stats([s['intervals'][k] for s in measured if k in s['intervals']]) for k in names})
            row['ratio'] = ratio(distributions['reference'], distributions['detailed'])
            row['ratio']['passed'] &= complete
            rows.append(row)
    return dict(verdict='qualified attribution' if all(r['ratio']['passed'] for r in rows) else 'no qualified attribution',
                attempted=len(samples), unattempted=[s['id'] for s in slots if s['id'] not in indexed], rows=rows)
