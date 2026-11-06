# SPDX-License-Identifier: GPL-3.0-or-later
"""Private invocation evidence validation; independent of Python assertions."""
import json
import platform
from pathlib import Path, PurePosixPath

from runtime_bundle import digest


VERSION = 2


def artifact_path(root, name):
    if Path(root).is_symlink():
        raise ValueError('symlink evidence root')
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or str(path) != name:
        raise ValueError('unsafe artifact path: ' + repr(name))
    current = Path(root)
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('symlink artifact: ' + name)
    if not current.is_file():
        raise ValueError('missing regular artifact: ' + name)
    return current


def inventory(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError('symlink artifact: ' + name)
        if name == 'report.json':
            continue
        if path.is_dir():
            continue
        artifact_path(root, name)
        result[name] = dict(size=path.stat().st_size, sha256=digest(path))
    return result


def validate_report(root, report, required, *, suite=None, options=None,
                    requirements=None, final=True):
    """Validate against caller-owned expectations, never child-owned requirements."""
    required = list(required)
    if not required:
        raise ValueError('empty expected scenario definitions')
    if final and report.get('status') != 'passed':
        raise ValueError('report is not finalized successfully')
    if len(required) != len(set(required)):
        raise ValueError('duplicate expected scenarios')
    if report.get('version') != VERSION or report.get('required_scenarios') != required:
        raise ValueError('invalid evidence contract')
    if not isinstance(report.get('suite'), str) or not report['suite']:
        raise ValueError('missing suite identity')
    if suite is not None and report['suite'] != suite:
        raise ValueError('unexpected suite identity')
    if not isinstance(report.get('options'), dict) or (options is not None and report['options'] != options):
        raise ValueError('unexpected invocation options')
    records = report.get('records', [])
    names = [record.get('name') for record in records]
    if len(names) != len(set(names)) or set(names) != set(required):
        raise ValueError('missing, unexpected or duplicate scenarios')
    if any(record.get('status') != 'passed' for record in records):
        raise ValueError('failed scenario')
    expected = report.get('artifacts')
    if not isinstance(expected, dict) or expected != inventory(root):
        raise ValueError('missing or altered artifacts')
    scopes = report.get('scopes')
    if not isinstance(scopes, dict):
        raise ValueError('missing scope records')
    if requirements is None:
        requirements = {name: dict(artifacts=[], scopes=[]) for name in required}
    if set(requirements) != set(required):
        raise ValueError('incomplete caller requirements')
    units = set()
    for identity, scope in scopes.items():
        unit = scope.get('unit')
        if unit is not None:
            if not isinstance(unit, str) or unit in units:
                raise ValueError('duplicate or invalid scope unit identity')
            units.add(unit)
        if scope.get('scenario') not in required:
            raise ValueError('scope has no required scenario')
        if scope.get('phase') == 'created':
            cleanup = scope.get('cleanup', {})
            if (scope.get('memory_max') != str(2 * 1024**3) or scope.get('swap_max') != '0'
                    or cleanup.get('scope_empty') is not True or type(cleanup.get('launcher_status')) is not int
                    or not unit or cleanup.get('unit') != unit
                    or scope.get('cgroup') != cleanup.get('cgroup')
                    or Path(scope.get('cgroup', '')).name != unit
                    or not (cleanup.get('cgroup_removed') is True
                            or cleanup.get('cgroup_events', {}).get('populated') == '0')
                    or cleanup.get('completed', float('inf')) - cleanup.get('started', 0) > 5):
                raise ValueError('invalid created scope proof: ' + identity)
        elif scope.get('phase') == 'absent':
            if not scope.get('cleanup', {}).get('unit_absent'):
                raise ValueError('unconfirmed absent scope')
        elif scope.get('phase') not in ('preflight-rejected', 'launcher-failed'):
            raise ValueError('incomplete scope lifecycle: ' + identity)
    for record in records:
        needed = requirements[record['name']]
        if record.get('required_artifacts') != needed['artifacts']:
            raise ValueError('unexpected scenario artifact requirements')
        declared_scopes = [identity for identity, scope in scopes.items() if scope.get('scenario') == record['name']]
        if record.get('required_scopes') != declared_scopes:
            raise ValueError('missing scenario scope declaration')
        observed = [identity for identity, scope in scopes.items()
                    if scope.get('scenario') == record['name'] and scope.get('phase') == 'created']
        if len(observed) < needed.get('min_scopes', 0):
            raise ValueError('missing required scope: ' + record['name'])
        if needed.get('cleanup_failure'):
            if (record.get('exception') != 'CleanupError'
                    or record.get('cleanup', {}).get('scope_empty') is not False
                    or record.get('test_scope_recovery', {}).get('scope_empty') is not True
                    or record.get('test_scope_recovery', {}).get('launcher_status') is None):
                raise ValueError('missing rejected cleanup and successful recovery proof')
        for name in needed['artifacts']:
            artifact_path(root, name)
            if name not in expected:
                raise ValueError('required artifact omitted: ' + name)
        for identity in needed['scopes']:
            scope = scopes.get(identity, {})
            cleanup = scope.get('cleanup', {})
            if (scope.get('memory_max') != str(2 * 1024**3)
                    or scope.get('swap_max') != '0'
                    or cleanup.get('scope_empty') is not True
                    or cleanup.get('launcher_status') is None
                    or not (cleanup.get('cgroup_removed') is True
                            or cleanup.get('cgroup_events', {}).get('populated') == '0')):
                raise ValueError('missing scope cleanup proof: ' + identity)


def validate_child(root, *, suite, options, required, requirements):
    root = Path(root)
    report = json.loads(artifact_path(root, 'report.json').read_text())
    if report.get('status') != 'passed':
        raise ValueError('child did not finalize successfully')
    validate_report(root, report, required, suite=suite, options=options,
                    requirements=requirements)
    return report


ACTIVE = None


def require(condition, detail='acceptance requirement failed'):
    if not condition:
        raise ValueError(str(detail))


class Invocation:
    """Checkpointed private report and scope recorder, including constructor errors."""
    def __init__(self, root, suite, options, required, requirements):
        global ACTIVE
        self.root = Path(root)
        self.required = list(required)
        self.requirements = requirements
        self.current = None
        self.runtime_bundle = None
        self.report = dict(version=VERSION, suite=suite, options=options,
                           platform=dict(system=platform.platform(), machine=platform.machine()),
                           required_scenarios=self.required, requirements=requirements,
                           records=[], scopes={}, artifacts={}, status='failed')
        ACTIVE = self
        self.checkpoint()

    def checkpoint(self):
        for record in self.report['records']:
            needed = self.requirements.get(record.get('name'), {})
            record['required_artifacts'] = needed.get('artifacts', [])
            record['required_scopes'] = [identity for identity, scope in self.report['scopes'].items()
                                         if scope.get('scenario') == record.get('name')]
        temporary = self.root / '.report.tmp'
        temporary.write_text(json.dumps(self.report, indent=2) + '\n')
        temporary.replace(self.root / 'report.json')

    def scenario(self, name):
        self.current = name
        self.checkpoint()

    def begin_scope(self, binary):
        identity = 'scope-' + str(len(self.report['scopes']))
        record = dict(identity=identity, scenario=self.current, binary=str(binary), phase='preflight')
        self.report['scopes'][identity] = record
        self.checkpoint()
        return record

    def finish(self, records, **extra):
        self.report.update(extra, records=records, status='failed')
        self.checkpoint()
        try:
            self.report['artifacts'] = inventory(self.root)
            validate_report(self.root, self.report, self.required,
                            suite=self.report['suite'], options=self.report['options'],
                            requirements=self.requirements, final=False)
            self.report['status'] = 'passed'
        except Exception as error:
            self.report['validation_error'] = repr(error)
            if all(record.get('status') == 'passed' for record in records):
                for record in records:
                    record.update(status='failed', finalization_error=repr(error))
        self.checkpoint()
        return self.report['status'] == 'passed'


def destination(args, build, prefix):
    import tempfile
    if args.evidence_dir is None:
        return Path(tempfile.mkdtemp(prefix=prefix, dir=build))
    root = args.evidence_dir.absolute()
    root.mkdir(parents=True, exist_ok=False)
    return root


def guarded_main(function):
    """Retain diagnostics for failures outside a scenario body as well."""
    try:
        return function()
    except Exception as error:
        if ACTIVE is not None:
            ACTIVE.report['unhandled_error'] = repr(error)
            ACTIVE.finish(ACTIVE.report['records'])
            ACTIVE.report['status'] = 'failed'
            ACTIVE.checkpoint()
        print(repr(error), flush=True)
        return 1
