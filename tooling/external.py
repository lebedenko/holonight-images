#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate declarations and check installed prerequisites without acquiring packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

BUNDLE = Path(__file__).resolve().parent
SCOPES = {'build', 'test', 'tool', 'runtime'}


def catalog():
    return json.loads((BUNDLE / 'external-packages.json').read_text())['dependencies']


def requirements(config, scopes=('build', 'tool'), features=None):
    definitions = catalog()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', config.get('module', '')):
        raise RuntimeError('Invalid module identifier')
    if any(not isinstance(value, bool) for value in config.get('external_features', {}).values()):
        raise RuntimeError(f'{config["module"]}: feature defaults must be boolean')
    selected = dict(config.get('external_features', {}))
    selected.update(features or {})
    result = []
    for item in config.get('external_dependencies', []):
        if item.get('id') not in definitions:
            raise RuntimeError(f'{config["module"]}: unknown external dependency {item.get("id")}')
        if not item.get('scope') or not set(item['scope']) <= SCOPES:
            raise RuntimeError(f'{config["module"]}: invalid scope for {item["id"]}')
        merged = {**definitions[item['id']], **item}
        if merged['discovery'] not in {'cmake', 'pkg-config', 'tool', 'runtime'}:
            raise RuntimeError(f'{config["module"]}: invalid discovery mechanism for {item["id"]}')
        version = merged.get('version')
        if version and not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*(?:\.\.\.<?[0-9]+(?:\.[0-9]+)*)?', version):
            raise RuntimeError(f'{config["module"]}: invalid version constraint {version}')
        for value in [merged['package'], *merged.get('components', []), *merged.get('targets', [])]:
            if not re.fullmatch(r'[A-Za-z0-9_:+.><=\-]+', value):
                raise RuntimeError(f'{config["module"]}: invalid discovery name {value}')
        controls = item.get('features', [item['feature']] if item.get('feature') else [])
        for feature in controls:
            if feature not in config.get('external_features', {}):
                raise RuntimeError(f'{config["module"]}: undeclared feature {feature}')
        if not set(item['scope']) & set(scopes) or not all(selected[feature] for feature in controls):
            continue
        mapped = {distribution: list(names) for distribution, names in merged['packages'].items()}
        for component in merged.get('components', []):
            for distribution, names in merged.get('component_packages', {}).get(component, {}).items():
                mapped[distribution].extend(names)
        merged['packages'] = {distribution: sorted(set(names)) for distribution, names in mapped.items()}
        result.append(merged)

    return result


def package_names(configs, distribution, scopes=('build', 'tool', 'runtime'), features=None):
    return sorted({name for config in configs for item in requirements(config, scopes, features)
                   for name in item['packages'][distribution]})


def external_prefix():
    value = os.environ.get('HOLONIGHT_EXTERNAL_PREFIX')
    if value:
        return Path(value).resolve()
    prepared = BUNDLE.parent / 'build/external/prefix'
    return prepared.resolve() if (prepared.parent / 'provider-state.json').is_file() else None


def discovery_environment(internal=None):
    env = dict(os.environ)
    locations = [p for p in (internal, external_prefix()) if p]
    for variable, suffixes in [('PKG_CONFIG_PATH', ('lib/pkgconfig', 'lib64/pkgconfig', 'share/pkgconfig')),
                               ('QML_IMPORT_PATH', ('lib/qt6/qml',))]:
        paths = [str(p / suffix) for p in locations for suffix in suffixes]
        if env.get(variable):
            paths.append(env[variable])
        if paths:
            env[variable] = os.pathsep.join(paths)
    return env


def probe_source(configs, scopes=('build', 'tool'), features=None):
    lines = ['cmake_minimum_required(VERSION 3.25)',
             'project(HoloNightExternalDependencies LANGUAGES C CXX)',
             'find_package(PkgConfig REQUIRED)']
    qt_private = set()
    evidence_variables = {'CMAKE_CXX_COMPILER', 'CMAKE_CXX_COMPILER_ID', 'CMAKE_CXX_COMPILER_VERSION',
                          'CMAKE_C_COMPILER', 'CMAKE_C_COMPILER_ID', 'CMAKE_C_COMPILER_VERSION'}
    for config in configs:
        for number, item in enumerate(requirements(config, scopes, features)):
            kind, package = item['discovery'], item['package']
            lines.append(f'# {config["module"]}: {item["id"]}')
            if kind == 'cmake':
                evidence_variables.update({package + '_DIR', package + '_VERSION', package + '_VERSION_STRING'})
                components = item.get('components', [])
                evidence_variables.update(package + c + suffix for c in components for suffix in ('_DIR', '_VERSION'))
                public = [c for c in components if not c.endswith('Private')]
                qt_private.update(c for c in components if c.endswith('Private')) if package == 'Qt6' else None
                args = [package]
                if item.get('version'):
                    args.append(item['version'])
                if package in {'GTest', 'QMarkdown', 'tomlplusplus', 'nlohmann_json'}:
                    args.append('CONFIG')
                args.append('REQUIRED')
                if public:
                    args.extend(['COMPONENTS', *public])
                lines.append('find_package(' + ' '.join(args) + ')')
                for target in item.get('targets', []):
                    lines += [f'if(NOT TARGET {target})',
                              f'  message(FATAL_ERROR "{config["module"]}: installed {package} lacks {target}")', 'endif()']
                if package == 'QMarkdown':
                    lines.extend(qmarkdown_checks())
            elif kind == 'pkg-config':
                prefix = f'External_{number}_{config["module"].replace("-", "_")}'
                lines.append(f'pkg_check_modules({prefix} REQUIRED {package})')
                evidence_variables.update(prefix + suffix for suffix in ('_VERSION', '_PREFIX', '_INCLUDE_DIRS', '_LIBRARY_DIRS'))
    if qt_private:
        lines.append('find_package(Qt6 ${Qt6_VERSION} EXACT REQUIRED COMPONENTS ' + ' '.join(sorted(qt_private)) + ')')
    lines += ['foreach(_variable IN ITEMS ' + ' '.join(sorted(evidence_variables)) + ')',
              '  file(APPEND "${CMAKE_BINARY_DIR}/resolved.txt" "${_variable}=${${_variable}}\\n")',
              'endforeach()']
    return '\n'.join(lines) + '\n'


def qmarkdown_checks():
    return ['get_target_property(_qmarkdown_type QMarkdown::QMarkdown TYPE)',
            'if(NOT _qmarkdown_type STREQUAL "SHARED_LIBRARY")',
            '  message(FATAL_ERROR "Files requires installed shared QMarkdown 1.x")', 'endif()',
            'foreach(_metadata qmldir QMarkdown.qmltypes)',
            '  if(NOT EXISTS "${QMarkdown_QML_IMPORT_PATH}/QMarkdown/${_metadata}")',
            '    message(FATAL_ERROR "Installed QMarkdown is missing QML metadata: ${_metadata}")',
            '  endif()', 'endforeach()']


def check(config, scopes=('build', 'tool'), features=None, evidence=None, cmake_options=None):
    items = requirements(config, scopes, features)
    missing = [item['package'] for item in items if item['discovery'] == 'tool' and not shutil.which(item['package'])]
    if missing:
        raise RuntimeError(f'{config["module"]}: missing tools {", ".join(missing)}. '
                           'Install prerequisites explicitly; task deps never installs or downloads them.')
    if not any(item['discovery'] in {'cmake', 'pkg-config'} for item in items):
        return {}
    with tempfile.TemporaryDirectory(prefix='holonight external check ') as directory:
        source = Path(directory)
        (source / 'CMakeLists.txt').write_text(probe_source([config], scopes, features))
        args = ['cmake', '-S', str(source), '-B', str(source / 'build'), '-G', 'Ninja']
        args.extend(f'-D{key}={value}' for key, value in (cmake_options or {}).items())
        if external_prefix():
            args.append('-DCMAKE_PREFIX_PATH=' + str(external_prefix()))
        completed = subprocess.run(args, env=discovery_environment(), capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(f'{config["module"]}: installed prerequisites unavailable. '
                               'Install the declared packages or set HOLONIGHT_EXTERNAL_PREFIX.\n' + completed.stdout + completed.stderr)
        resolved = (source / 'build/resolved.txt').read_text().splitlines()
        signatures = {}
        for line in resolved:
            key, value = line.split('=', 1)
            if key.endswith('_DIR') and value and Path(value).is_dir():
                files = sorted(Path(value).glob('*.cmake'))
                signatures[key] = hashlib.sha256(b''.join(p.name.encode() + p.read_bytes() for p in files)).hexdigest()
        result = {'module': config['module'], 'features': config.get('external_features', {}) | (features or {}),
                  'external_prefix': str(external_prefix()) if external_prefix() else None,
                  'requirements': items, 'resolved': resolved, 'package_config_signatures': signatures}
        if evidence:
            from compilation import atomic_json
            atomic_json(evidence, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate', 'check', 'packages', 'probe'])
    parser.add_argument('--module', type=Path, action='append', required=True)
    parser.add_argument('--distribution', choices=['arch', 'debian'], default='arch')
    parser.add_argument('--scope', action='append', choices=sorted(SCOPES))
    parser.add_argument('--feature', action='append', default=[], metavar='OPTION=ON|OFF')
    args = parser.parse_args()
    configs = [json.loads(path.read_text()) for path in args.module]
    features = {}
    for value in args.feature:
        key, enabled = value.split('=', 1)
        if enabled not in {'ON', 'OFF'}:
            parser.error('features require OPTION=ON|OFF')
        features[key] = enabled == 'ON'
    scopes = args.scope or ['build', 'tool', 'runtime']
    if args.command == 'packages':
        print('\n'.join(package_names(configs, args.distribution, scopes, features)))
    elif args.command == 'probe':
        print(probe_source(configs, scopes, features), end='')
    else:
        for config in configs:
            requirements(config, SCOPES, features)
            if args.command == 'check':
                check(config, scopes, features)
            print(config['module'] + ': valid')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        raise SystemExit(str(exc))
