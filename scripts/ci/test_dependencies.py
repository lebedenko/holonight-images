#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline installed discovery and cache regressions, with real CMake probes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tooling'))
import external


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='images dependencies with spaces ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source with spaces'
        shutil.copytree(ROOT, self.source, ignore=shutil.ignore_patterns(
            '.git', 'build', '.cache', '__pycache__', 'compile_commands.json'))
        self.empty = self.root / 'empty'
        self.empty.mkdir()
        self.env = dict(os.environ)
        for name in ('HOLONIGHT_EXTERNAL_PREFIX', 'HOLONIGHT_DEPENDENCY_PREFIX', 'PKG_CONFIG_PATH',
                     'PKG_CONFIG_LIBDIR', 'PKG_CONFIG_SYSROOT_DIR', 'HOLONIGHT_BUILD_FEATURES'):
            self.env.pop(name, None)

    def command(self, args, env=None):
        return subprocess.run(args, cwd=self.source, env=env or self.env, text=True, capture_output=True)

    def configure(self, *options):
        return self.command(['cmake', '-S', '.', '-B', 'build/direct', '-G', 'Ninja', *options])

    def assert_pass(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_libexif_rejected(self):
        env = dict(self.env, PKG_CONFIG_LIBDIR=str(self.empty))
        result = self.command(['cmake', '-S', '.', '-B', 'build/missing', '-G', 'Ninja',
                               '-DPKG_CONFIG_USE_CMAKE_PREFIX_PATH=OFF'], env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('libexif', result.stdout + result.stderr)

    def test_missing_libwebp_rejected(self):
        installed = Path(subprocess.check_output(['pkg-config', '--variable=pcfiledir', 'libexif'], text=True).strip())
        shutil.copyfile(installed / 'libexif.pc', self.empty / 'libexif.pc')
        env = dict(self.env, PKG_CONFIG_LIBDIR=str(self.empty))
        result = self.command(['cmake', '-S', '.', '-B', 'build/missing', '-G', 'Ninja',
                               '-DPKG_CONFIG_USE_CMAKE_PREFIX_PATH=OFF'], env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('libwebp', result.stdout + result.stderr)

    def test_normal_commands_fail_without_preparing_or_acquiring(self):
        env = dict(self.env, PKG_CONFIG_LIBDIR=str(self.empty))
        for command in ('configure', 'build', 'test'):
            with self.subTest(command=command):
                result = self.command(['python3', 'tooling/workflow.py', command, '--preset', 'test'], env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('libexif', result.stdout + result.stderr)
                self.assertFalse((self.source / 'build/deps').exists())
                self.assertFalse((self.source / 'build/external').exists())
                self.assertFalse((self.source / 'build/test/CMakeCache.txt').exists())

    def test_task_deps_checks_without_provider_builds(self):
        self.assert_pass(self.command(['task', 'deps', 'PRESET=test']))
        evidence = json.loads((self.source / 'build/deps/external-state.json').read_text())
        self.assertEqual(evidence['module'], 'holonight-images')
        self.assertFalse((self.source / 'build/deps/prefix').exists())
        self.assertFalse((self.source / 'build/external').exists())

    def test_tests_disabled_does_not_require_gtest(self):
        self.assert_pass(self.configure('-DBUILD_TESTING=OFF', '-DCMAKE_DISABLE_FIND_PACKAGE_GTest=TRUE'))

    def test_tests_enabled_requires_gtest(self):
        result = self.configure('-DBUILD_TESTING=ON', '-DCMAKE_DISABLE_FIND_PACKAGE_GTest=TRUE')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('GTest', result.stdout + result.stderr)

    def incompatible_package(self, package, version, requirement):
        directory = self.root / 'old prefix' / 'lib/cmake' / package
        directory.mkdir(parents=True)
        (directory / f'{package}Config.cmake').write_text('')
        (directory / f'{package}ConfigVersion.cmake').write_text(
            f'set(PACKAGE_VERSION {version})\n'
            'if(PACKAGE_VERSION VERSION_LESS PACKAGE_FIND_VERSION)\n'
            '  set(PACKAGE_VERSION_COMPATIBLE FALSE)\n'
            'else()\n  set(PACKAGE_VERSION_COMPATIBLE TRUE)\nendif()\n')
        if package == 'Qt6':
            # Project hooks run after compiler discovery and before dependency lookup.
            isolation = self.root / 'isolate packages.cmake'
            isolation.write_text('set(CMAKE_FIND_USE_CMAKE_SYSTEM_PATH FALSE)\n'
                                 'set(CMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH FALSE)\n')
            result = self.configure(f'-DQt6_DIR={directory}', f'-DCMAKE_PROJECT_INCLUDE={isolation}')
        else:
            # Limit only GTest discovery; other installed prerequisites remain available.
            isolation = self.root / 'isolate gtest.cmake'
            isolation.write_text('macro(find_package)\n'
                                 '  if("${ARGV0}" STREQUAL "GTest")\n'
                                 f'    _find_package(${{ARGV}} PATHS "{directory}" NO_DEFAULT_PATH)\n'
                                 '  else()\n    _find_package(${ARGV})\n  endif()\nendmacro()\n')
            result = self.configure('-DBUILD_TESTING=ON', f'-DGTest_DIR={directory}',
                                    f'-DCMAKE_PROJECT_INCLUDE={isolation}')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(requirement, result.stdout + result.stderr)

    def test_old_qt_rejected(self):
        self.incompatible_package('Qt6', '6.10.0', '6.11')

    def test_old_gtest_rejected(self):
        self.incompatible_package('GTest', '1.13.0', '1.14')

    def test_system_discovery_with_empty_internal_prefix(self):
        self.assert_pass(self.configure('-DBUILD_TESTING=ON', f'-DHOLONIGHT_DEPENDENCY_PREFIX={self.empty}'))

    def test_explicit_prefix_spaces_and_changed_identity_archive_cache(self):
        prefix = self.root / 'external prefix'
        pc_dir = prefix / 'lib/pkgconfig'
        pc_dir.mkdir(parents=True)
        for package in ('libexif', 'libwebp', 'libsharpyuv'):
            installed = Path(subprocess.check_output(['pkg-config', '--variable=pcfiledir', package], text=True).strip())
            shutil.copyfile(installed / f'{package}.pc', pc_dir / f'{package}.pc')
        env = dict(self.env, HOLONIGHT_EXTERNAL_PREFIX=str(prefix), PKG_CONFIG_LIBDIR=str(self.empty))
        args = ['python3', 'tooling/workflow.py', 'configure', '--preset', 'test']
        self.assert_pass(self.command(args, env))
        marker = self.source / 'build/test/previous-marker'
        marker.write_text('preserved')
        # A different explicit prefix is a different compatibility identity.
        second = self.root / 'second external prefix'
        shutil.copytree(prefix, second)
        env['HOLONIGHT_EXTERNAL_PREFIX'] = str(second)
        self.assert_pass(self.command(args, env))
        self.assertEqual((self.source / 'build/test.previous-1/previous-marker').read_text(), 'preserved')
        self.assertFalse(marker.exists())
        self.assertFalse((self.source / 'build/deps').exists())

    def test_installed_gtest_config_prefix_with_spaces(self):
        directory = self.root / 'lib/cmake/GTest'
        directory.mkdir(parents=True)
        (directory / 'GTestConfig.cmake').write_text('add_library(GTest::gtest INTERFACE IMPORTED)\n')
        (directory / 'GTestConfigVersion.cmake').write_text(
            'set(PACKAGE_VERSION 1.14.0)\nset(PACKAGE_VERSION_COMPATIBLE TRUE)\n')
        config = {'module': 'fixture', 'external_dependencies':
                  [{'id': 'gtest', 'scope': ['test'], 'targets': ['GTest::gtest']}]}
        with patch.dict(os.environ, {'HOLONIGHT_EXTERNAL_PREFIX': str(self.root)}):
            evidence = external.check(config, ('test',))
        self.assertIn('GTest_DIR=' + str(directory), evidence['resolved'])


if __name__ == '__main__':
    unittest.main()
