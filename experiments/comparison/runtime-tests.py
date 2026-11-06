#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runtime preflight regressions, independent of sandbox availability."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runtime_bundle as runtime
from harness import Worker


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.binary = self.root / 'worker'
        self.binary.write_bytes(b'worker')
        self.binary.chmod(0o755)
        self.bundle = self.root / 'bundle'
        self.file = self.bundle / 'usr/bin/worker'
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b'worker')
        self.file.chmod(0o755)
        self.manifest = dict(version=1, provenance={}, files=[dict(
            path='usr/bin/worker', destination='/usr/bin/worker', size=6,
            mode=0o755, sha256=runtime.digest(self.file))], entries={str(self.binary): dict(
                destination='/usr/bin/worker', role='qt', sha256=runtime.digest(self.file))})
        for target in sorted(runtime.REQUIRED):
            path = self.bundle / target.lstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(runtime.loader_configuration().encode() if target == runtime.CONFIGURATION else b'runtime')
            path.chmod(0o755 if target in runtime.EXECUTABLES else 0o644)
            self.manifest['files'].append(dict(path=target.lstrip('/'), destination=target,
                size=path.stat().st_size, mode=path.stat().st_mode & 0o777, sha256=runtime.digest(path)))
        self.save()

    def save(self):
        (self.bundle / runtime.MANIFEST).write_text(json.dumps(self.manifest))

    def rejected(self):
        with patch('harness.subprocess.Popen') as popen:
            with self.assertRaises((ValueError, OSError, TypeError, KeyError)):
                Worker(self.binary, runtime_bundle=self.bundle)
            popen.assert_not_called()

    def test_valid(self):
        runtime.validate(self.bundle, self.binary)

    def test_missing_bundle(self):
        self.bundle = self.root / 'missing'
        self.rejected()

    def test_invalid_manifests(self):
        original = copy.deepcopy(self.manifest)
        for key, value in [('version', 2), ('files', []), ('entries', []), ('provenance', None)]:
            with self.subTest(key=key):
                self.manifest = copy.deepcopy(original)
                self.manifest[key] = value
                self.save()
                self.rejected()

    def test_destinations(self):
        for target in ['/usr/../escape', '/tmp/escape', '//usr/foo', 'relative']:
            with self.subTest(target=target):
                self.manifest['files'][0]['destination'] = target
                self.save()
                self.rejected()

    def test_collision(self):
        self.manifest['files'] *= 2
        self.save()
        self.rejected()

    def test_unexpected(self):
        (self.bundle / 'canary').write_text('unexpected')
        self.rejected()

    def test_unexpected_directory(self):
        (self.bundle / 'canary').mkdir()
        self.rejected()

    def test_symlink(self):
        self.file.unlink()
        self.file.symlink_to(self.binary)
        self.rejected()

    def test_hash(self):
        self.file.write_bytes(b'change')
        self.rejected()

    def test_mode(self):
        self.file.chmod(0o644)
        self.rejected()

    def test_missing_file(self):
        self.file.unlink()
        self.rejected()

    def test_identity(self):
        self.binary.write_bytes(b'changed')
        self.rejected()

    def test_unknown_entry(self):
        self.manifest['entries'] = {}
        self.save()
        self.rejected()

    def test_role(self):
        self.manifest['entries'][str(self.binary)]['role'] = 'glycin'
        self.save()
        self.rejected()

    def test_missing_dependencies_no_publication(self):
        output = self.root / 'output'
        with self.assertRaises(ValueError):
            runtime.prepare(self.root / 'missing', output)
        self.assertFalse(output.exists())

    def test_unresolved_library(self):
        with patch('runtime_bundle.subprocess.run') as run:
            run.return_value.stdout = 'libmissing.so => not found\n'
            with self.assertRaises(ValueError):
                runtime.dependencies([self.binary])

    def test_existing_output_preserved(self):
        with self.assertRaises(ValueError):
            runtime.prepare(self.root, self.bundle)
        self.assertTrue(self.file.exists())

    def test_incomplete_inventory(self):
        self.manifest['files'] = [r for r in self.manifest['files'] if r['destination'] != '/usr/bin/bwrap']
        (self.bundle / 'usr/bin/bwrap').unlink()
        self.save()
        self.rejected()

    def test_manifest_symlink(self):
        manifest = self.bundle / runtime.MANIFEST
        copy = self.root / 'manifest-copy'
        manifest.rename(copy)
        manifest.symlink_to(copy)
        self.rejected()

    def test_manifest_mode(self):
        (self.bundle / runtime.MANIFEST).chmod(0o600)
        self.rejected()

    def test_launcher_creation_failure_releases_resources(self):
        worker = Worker.__new__(Worker)
        with patch('harness.subprocess.Popen', side_effect=OSError('launcher unavailable')):
            with self.assertRaisesRegex(OSError, 'launcher unavailable'):
                worker.__init__(self.binary, runtime_bundle=self.bundle)
        self.assertTrue(worker.stderr.closed)
        self.assertFalse(Path(worker.temporary.name).exists())
        self.assertIsNone(worker.cleanup)

    def test_constructor_failure_is_retained_in_invocation(self):
        from runtime_evidence import Invocation
        with patch('runtime_evidence.ACTIVE', None):
            needed = {'launcher': dict(artifacts=[], scopes=[], min_scopes=0)}
            invocation = Invocation(self.root, 'constructor', {}, needed, needed)
            invocation.scenario('launcher')
            invocation.report['records'].append(dict(name='launcher', status='passed'))
            with patch('harness.subprocess.Popen', side_effect=OSError('launcher unavailable')):
                with self.assertRaises(OSError):
                    Worker(self.binary, runtime_bundle=self.bundle)
            self.assertTrue(invocation.finish(invocation.report['records']))
            recorded = json.loads((self.root / 'report.json').read_text())
            scope = next(iter(recorded['scopes'].values()))
            self.assertEqual(scope['phase'], 'launcher-failed')
            self.assertIn('launcher unavailable', scope['constructor_error'])

    def test_preparation_collision(self):
        files = {}
        runtime.copy_file(self.root / 'staging', files, self.binary, '/usr/bin/one')
        runtime.copy_file(self.root / 'staging', files, self.binary, '/usr/bin/one')
        other = self.root / 'other'
        other.write_bytes(b'different')
        with self.assertRaises(ValueError):
            runtime.copy_file(self.root / 'staging', files, other, '/usr/bin/one')
        with self.assertRaises(ValueError):
            runtime.copy_file(self.root / 'staging', files, other, '/usr/bin/one/child')

    def test_aliases_are_regular(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.binary)
        files = {}
        runtime.copy_file(self.root / 'staging', files, alias, '/usr/lib/alias')
        copied = self.root / 'staging/usr/lib/alias'
        self.assertFalse(copied.is_symlink())
        self.assertEqual(copied.read_bytes(), b'worker')
        self.assertEqual(runtime.normalized(Path('/lib/libtest.so')), '/usr/lib/libtest.so')

    def test_atomic_publication(self):
        stage = self.root / 'stage'
        stage.mkdir()
        (stage / 'complete').write_text('complete')
        output = self.root / 'published'
        runtime.publish(stage, output)
        self.assertEqual((output / 'complete').read_text(), 'complete')
        other = self.root / 'other-stage'
        other.mkdir()
        with self.assertRaises(FileExistsError):
            runtime.publish(other, output)
        self.assertTrue(other.exists())
        self.assertEqual((output / 'complete').read_text(), 'complete')

    def test_failed_publication(self):
        output = self.root / 'unpublished'
        with self.assertRaises(FileNotFoundError):
            runtime.publish(self.root / 'missing-stage', output)
        self.assertFalse(output.exists())

    def test_environment(self):
        with patch.dict('os.environ', {'PATH': '/canary', 'LD_PRELOAD': '/canary',
                                     'QT_PLUGIN_PATH': '/canary', 'GLYCIN_DATA_DIR': '/canary',
                                     'XDG_DATA_HOME': '/canary'}):
            env = runtime.host_environment()
        self.assertEqual(env['PATH'], '/usr/bin')
        self.assertFalse(set(env) & {'LD_PRELOAD', 'QT_PLUGIN_PATH', 'GLYCIN_DATA_DIR', 'XDG_DATA_HOME'})


class EvidenceTests(unittest.TestCase):
    def test_execution_interleaving(self):
        from runtime_trace import successful_executions
        trace = ('1 execve("/worker", [], [] <unfinished ...>\n'
                 '2 execve("/missing", [], []) = -1 ENOENT (missing)\n'
                 '1 <... execve resumed>) = 0\n')
        self.assertEqual(successful_executions(trace), ['/worker'])

    def test_incomplete_execution(self):
        from runtime_trace import successful_executions
        for trace in ('', '1 execve("/worker", [], [] <unfinished ...>',
                      '1 <... execve resumed>) = 0', '1 execve("/worker", []'):
            with self.subTest(trace=trace), self.assertRaises(ValueError):
                successful_executions(trace)

    def test_nested_report_is_inventoried(self):
        from runtime_evidence import inventory
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'child').mkdir()
            (root / 'report.json').write_text('{}')
            (root / 'child/report.json').write_text('{}')
            self.assertEqual(set(inventory(root)), {'child/report.json'})

    def test_symlink_artifact_rejected(self):
        from runtime_evidence import inventory
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'target').write_text('proof')
            (root / 'alias').symlink_to(root / 'target')
            with self.assertRaises(ValueError):
                inventory(root)

    def test_independent_requirements(self):
        from runtime_evidence import validate_report
        with tempfile.TemporaryDirectory() as directory:
            report = dict(version=2, status='passed', suite='test', options={}, scopes={},
                          required_scenarios=['control'],
                          records=[dict(name='control', status='passed', required_artifacts=[], required_scopes=[])], artifacts={})
            for needed in (dict(artifacts=['omitted'], scopes=[]),
                           dict(artifacts=[], scopes=['omitted'])):
                with self.subTest(needed=needed), self.assertRaises(ValueError):
                    validate_report(Path(directory), report, ['control'],
                                    requirements={'control': needed})
            with self.assertRaises(ValueError):
                validate_report(Path(directory), report, ['control'], suite='wrong')

    def test_report_contract(self):
        from runtime_evidence import inventory, validate_report
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / 'proof'
            artifact.write_text('proof')
            report = dict(version=2, status='passed', suite='test', options={}, scopes={}, required_scenarios=['control'],
                          records=[dict(name='control', status='passed', required_artifacts=[], required_scopes=[])], artifacts=inventory(root))
            validate_report(root, report, ['control'])
            for records in ([], report['records'] * 2, [dict(name='control', status='failed')]):
                with self.assertRaises(ValueError):
                    validate_report(root, dict(report, records=records), ['control'])
            artifact.write_text('altered')
            with self.assertRaises(ValueError):
                validate_report(root, report, ['control'])


class TraceTests(unittest.TestCase):
    def parse(self, text, **kwargs):
        from runtime_trace import analyze
        return analyze(text, **kwargs)

    def test_arguments_are_not_accesses(self):
        result = self.parse('1 execve("/worker", ["/protected/mentioned"], []) = 0', protected=['/protected'])
        self.assertFalse(result['protected_operations'])

    def test_path_results_and_escaped_names(self):
        result = self.parse('1 openat(AT_FDCWD, "/protected/a\\nfile", O_RDONLY) = 3</protected/a>\n'
                            '1 access("/protected/missing", R_OK) = -1 ENOENT (missing)', protected=['/protected'])
        self.assertEqual(len(result['protected_operations']), 1)
        self.assertEqual(result['events'][0]['paths'], ['/protected/a\nfile'])
        self.assertEqual(result['events'][1]['classification'], 'lookup-probe')

    def test_directory_descriptors_and_process_inheritance(self):
        result = self.parse('1 chdir("/base") = 0\n'
                            '1 openat(AT_FDCWD, "child", O_RDONLY|O_DIRECTORY) = 3</base/child>\n'
                            '1 dup(3</base/child>) = 7</base/child>\n'
                            '1 clone(child_stack=NULL, flags=SIGCHLD) = 2\n'
                            '2 openat(7, "file", O_RDONLY) = 4</base/child/file>\n'
                            '2 close(7) = 0\n'
                            '2 openat(AT_FDCWD, "other", O_RDONLY) = 5</base/other>')
        self.assertEqual(result['events'][4]['paths'], ['/base/child/file'])
        self.assertEqual(result['events'][6]['paths'], ['/base/other'])

    def test_pid_namespace_translation(self):
        result = self.parse('100 [56] clone(child_stack=NULL, flags=SIGCHLD) = 2 /* 101 in strace\'s PID NS */\n'
                            '101 [80] chdir("/child") = 0\n'
                            '101 [56] clone(child_stack=NULL, flags=SIGCHLD) = 2 /* 102 in strace\'s PID NS */\n'
                            '102 [257] openat(AT_FDCWD, "file", O_RDONLY) = 3')
        self.assertEqual(result['events'][-1]['paths'], ['/child/file'])
        self.assertEqual(result['events'][2]['child_pid'], 102)

    def test_child_changes_directory_before_parent_clone_resumes(self):
        result = self.parse('1 chdir("/base") = 0\n'
                            '1 clone(child_stack=NULL, flags=SIGCHLD <unfinished ...>\n'
                            '2 chdir("child") = 0\n'
                            '1 <... clone resumed>) = 2\n'
                            '2 openat(AT_FDCWD, "file", O_RDONLY) = 3')
        self.assertEqual(result['events'][-1]['paths'], ['/base/child/file'])

    def test_unresolved_or_truncated_critical_records(self):
        for text in ('1 openat(7, "file", O_RDONLY) = 3',
                     '1 openat(AT_FDCWD, "/truncated"..., O_RDONLY) = 3',
                     '1 connect(3, {} <unfinished ...>\n1 +++ killed by SIGKILL +++',
                     '1 execve("/worker", [], []) = ?',
                     '1 execve("/worker", [], []) = 0garbage',
                     '1 openat(AT_FDCWD, "/file", O_RDONLY) = -1'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_noncritical_terminated_call(self):
        result = self.parse('1 read(3, <unfinished ...>\n1 +++ killed by SIGTERM +++')
        self.assertEqual(result['interrupted'][0]['syscall'], 'read')

    def test_attempted_nested_exec_is_not_success(self):
        from runtime_trace import require_trial
        trace = ('1 execve("/usr/bin/bwrap", [], []) = 0\n'
                 '2 execve("/worker", [], []) = 0\n'
                 '3 execve("/usr/bin/bwrap", [], []) = -1 ENOENT (missing)\n'
                 '4 execve("/loader", [], []) = 0')
        with self.assertRaises(ValueError):
            require_trial(self.parse(trace), '/worker', '/loader')
        require_trial(self.parse(trace.replace('-1 ENOENT (missing)', '0')), '/worker', '/loader')

    def test_stage_contract_rejects_eof_and_wrong_stage(self):
        from runtime_trace import require_failure
        cases = ['1 execve("/worker", [], []) = 0',
                 '1 execve("/replacement", [], []) = 0\n1 +++ exited with 0 +++',
                 '1 execve("/replacement", [], []) = -1 EACCES (denied)']
        for trace in cases:
            with self.subTest(trace=trace), self.assertRaises(ValueError):
                require_failure(self.parse(trace), stage='outer', kind='failed', worker='/worker',
                                replacement='/replacement', diagnostic='EOF', load=None, status=1)
        trace = '1 execve("/replacement", [], []) = 0\n1 +++ exited with 1 +++'
        require_failure(self.parse(trace), stage='outer', kind='failed', worker='/worker',
                        replacement='/replacement', diagnostic='', load=None, status=1)

    def test_native_control_expectations_fail_closed(self):
        from runtime_controls import CHANNELS, expect
        for channel in CHANNELS:
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                expect(channel, {}, '')

    def test_deleted_return_descriptor_and_hexadecimal_result(self):
        result = self.parse('1 openat(AT_FDCWD, "/file", O_RDONLY) = 5</file>(deleted)\n'
                            '1 fcntl(5</file>(deleted), F_GETFL) = 0x8000 (flags O_RDONLY|O_LARGEFILE)\n'
                            '1 fcntl(5</file>(deleted), F_DUPFD_CLOEXEC, 3) = 6</file>(deleted)')
        self.assertEqual(result['events'][0]['returncode'], 5)
        self.assertEqual(result['events'][1]['returncode'], 32768)
        self.assertEqual(result['events'][2]['returncode'], 6)

    def test_deleted_descriptor_and_root_changes(self):
        result = self.parse('1 statx(6</memfd:frame>(deleted), "", AT_EMPTY_PATH, STATX_ALL, {}) = 0\n'
                            '1 chdir("/tmp") = 0\n'
                            '1 pivot_root("/tmp", "oldroot") = 0\n'
                            '1 openat(AT_FDCWD, "/oldroot/protected/file", O_RDONLY) = 3',
                            protected=['/protected'])
        self.assertEqual(result['events'][0]['paths'], ['/memfd:frame'])
        self.assertEqual(result['protected_operations'][0]['canonical_paths'], ['/protected/file'])

    def test_numbered_unknown_syscalls_remain_unresolved(self):
        for number in (-1, 0, 11, 46, 202, 233, 257):
            with self.subTest(number=number), self.assertRaises(ValueError):
                self.parse(f'1 [231] exit_group(0 <unfinished ...>\n1 [{number}] ???( <unfinished ...>\n1 +++ exited with 0 +++')

    def test_unknown_syscall_is_incomplete_proof(self):
        with self.assertRaises(ValueError):
            self.parse('1 ???( <unfinished ...>\n1 +++ exited with 0 +++')

    def test_missing_scope_cleanup_proof(self):
        from runtime_evidence import validate_report
        with tempfile.TemporaryDirectory() as directory:
            report = dict(version=2, status='passed', suite='test', options={}, required_scenarios=['control'], artifacts={},
                          records=[dict(name='control', status='passed', required_artifacts=[], required_scopes=['s'])],
                          scopes={'s': dict(scenario='control', phase='created', memory_max=str(2 * 1024**3), swap_max='0')})
            with self.assertRaises(ValueError):
                validate_report(Path(directory), report, ['control'])

    def test_scope_cleanup_must_match_unit_and_budget(self):
        from runtime_evidence import validate_report
        with tempfile.TemporaryDirectory() as directory:
            group = '/sys/fs/cgroup/image-comparison-fixture.scope'
            scope = dict(unit='image-comparison-fixture.scope', scenario='control', phase='created',
                         cgroup=group, memory_max=str(2 * 1024**3), swap_max='0',
                         cleanup=dict(unit='image-comparison-fixture.scope', cgroup=group,
                                      scope_empty=True, launcher_status=0, cgroup_removed=True,
                                      started=0, completed=1))
            report = dict(version=2, status='passed', suite='test', options={}, artifacts={},
                          required_scenarios=['control'], scopes={'s': scope},
                          records=[dict(name='control', status='passed', required_artifacts=[], required_scopes=['s'])])
            needed = {'control': dict(artifacts=[], scopes=[], min_scopes=1)}
            validate_report(Path(directory), report, ['control'], requirements=needed)
            for mutation in (dict(unit='another.scope'), dict(completed=5.001), dict(launcher_status='unreaped')):
                altered = copy.deepcopy(report)
                altered['scopes']['s']['cleanup'].update(mutation)
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    validate_report(Path(directory), altered, ['control'], requirements=needed)
            report['scopes']['duplicate'] = copy.deepcopy(scope)
            report['records'][0]['required_scopes'].append('duplicate')
            with self.assertRaises(ValueError):
                validate_report(Path(directory), report, ['control'], requirements=needed)

    def test_altered_child_report_is_detected_by_parent_inventory(self):
        from runtime_evidence import inventory, validate_report
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'child').mkdir()
            child = root / 'child/report.json'
            child.write_text('{}')
            report = dict(version=2, status='passed', suite='test', options={}, scopes={}, required_scenarios=['control'],
                          records=[dict(name='control', status='passed', required_artifacts=['child/report.json'], required_scopes=[])],
                          artifacts=inventory(root))
            requirements = {'control': dict(artifacts=['child/report.json'], scopes=[])}
            validate_report(root, report, ['control'], requirements=requirements)
            child.write_text('{"status":"changed"}')
            with self.assertRaises(ValueError):
                validate_report(root, report, ['control'], requirements=requirements)

    def test_child_contract_counts(self):
        from runtime_suites import scenarios
        for suite, options, count in [('cancellation', {'focused': False}, 35), ('capture', {}, 16),
                                      ('linked', {'focused': False}, 36),
                                      ('check', {'filter': 'protocol'}, 5), ('check', {'filter': 'capsule'}, 16)]:
            names = scenarios(suite, options)
            self.assertEqual(len(names), count)
            self.assertEqual(len(names), len(set(names)))

    def test_absent_and_malformed_child_report(self):
        from runtime_evidence import validate_child
        with tempfile.TemporaryDirectory() as directory:
            for payload in (None, 'invalid', '{}'):
                root = Path(directory)
                if payload is not None:
                    (root / 'report.json').write_text(payload)
                with self.subTest(payload=payload), self.assertRaises((ValueError, OSError)):
                    validate_child(root, suite='test', options={}, required=[], requirements={})

    def test_escaping_required_artifact(self):
        from runtime_evidence import artifact_path
        with tempfile.TemporaryDirectory() as directory:
            for name in ('../escape', '/absolute', 'a/../escape', './report.json'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    artifact_path(Path(directory), name)


if __name__ == '__main__':
    unittest.main()
