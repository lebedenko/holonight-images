#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable HoloNight developer workflow. Module settings live in module.json."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from compilation import atomic_json, merge
from external import check as check_external, discovery_environment, external_prefix, requirements as external_requirements

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT, **kwargs)


def settings():
    config = json.loads((ROOT / 'tooling/module.json').read_text())
    if 'external_dependencies' not in config:
        raise RuntimeError('Tooling 2.0 requires external dependency declarations in module.json. '
                           'Adopt the module metadata before synchronizing this bundle.')
    return config


def prefix():
    return Path(os.environ.get('HOLONIGHT_DEPENDENCY_PREFIX', ROOT / 'build/deps/prefix')).resolve()


def configured_prefix(preset='test'):
    if os.environ.get('HOLONIGHT_DEPENDENCY_PREFIX'):
        return prefix()
    cache = ROOT / 'build' / preset / 'CMakeCache.txt'
    if cache.is_file():
        match = re.search(r'^CMAKE_PREFIX_PATH:(?:STRING|UNINITIALIZED|PATH)=(.*)$', cache.read_text(), re.M)
        if match and match[1]:
            return Path(match[1].split(';')[0]).resolve()
    return prefix()


def cmake_prefixes(location):
    return ";".join(str(p) for p in (location, external_prefix()) if p)


def packages(config, location):
    result = {}
    for dep in config.get('dependencies', []):
        package = dep['package']
        candidates = sorted(location.glob(f'lib*/cmake/{package}/{package}Config.cmake'))
        candidates += sorted(location.glob(f'share/{package}/cmake/{package}Config.cmake'))
        if not candidates:
            raise RuntimeError(f'Missing {package} in {location}. Run task deps with local source overrides, '
                               'or supply HOLONIGHT_DEPENDENCY_PREFIX containing all providers.')
        unique = {p.resolve() for p in candidates}
        if len(unique) > 1:
            raise RuntimeError(f'Conflicting {package} packages in {location}: ' + ', '.join(map(str, sorted(unique))))
        result[package] = candidates[0].parent
    return result


def dependency_source(dep):
    key = dep['source_variable']
    source = Path(os.environ.get(key, ROOT.parent / dep['module'])).resolve()
    if not (source / 'CMakeLists.txt').is_file():
        raise RuntimeError(f'Missing {dep["module"]} source: {source}. Set {key} to a local checkout, '
                           'or supply HOLONIGHT_DEPENDENCY_PREFIX. Sources are never downloaded.')
    return source


def preset_variables(preset):
    path = ROOT / 'CMakePresets.json'
    if not preset or not path.is_file():
        return {}
    definitions = {item['name']: item for item in json.loads(path.read_text()).get('configurePresets', [])}
    def variables(name, visiting=()):
        if name in visiting:
            raise RuntimeError('CMake preset inheritance cycle: ' + name)
        item = definitions.get(name, {})
        parents = item.get('inherits', [])
        if isinstance(parents, str):
            parents = [parents]
        result = {}
        for parent in reversed(parents):
            result.update(variables(parent, (*visiting, name)))
        result.update(item.get('cacheVariables', {}))
        return result
    return variables(preset)


def build_context(preset):
    result = {}
    for key, value in preset_variables(preset).items():
        if not (re.fullmatch(r'CMAKE_(?:C|CXX)_COMPILER|CMAKE_TOOLCHAIN_FILE|CMAKE_(?:C|CXX|EXE_LINKER|SHARED_LINKER)_FLAGS(?:_\w+)?', key)
                or re.fullmatch(r'Qt6\w*_DIR|Python3_EXECUTABLE', key)):
            continue
        if isinstance(value, dict):
            value = value['value']
        value = str(value).replace('${sourceDir}', str(ROOT))
        value = re.sub(r'\$env\{([^}]+)\}', lambda match: os.environ.get(match[1], ''), value)
        result[key] = value
    return result


def selected_features(config, preset=None):
    selected = dict(config.get('external_features', {}))
    for key, value in preset_variables(preset).items():
        if key in selected:
            if isinstance(value, dict):
                value = value['value']
            if str(value).upper() not in {'ON', 'OFF', 'TRUE', 'FALSE', '1', '0'}:
                raise RuntimeError(f'Feature {key} must have an explicit boolean value')
            selected[key] = str(value).upper() in {'ON', 'TRUE', '1'}
    for assignment in shlex.split(os.environ.get('HOLONIGHT_BUILD_FEATURES', '')):
        key, value = assignment.split('=', 1)
        if key not in selected or value not in {'ON', 'OFF'}:
            raise RuntimeError(f'Invalid feature {assignment}; use declared OPTION=ON|OFF values')
        selected[key] = value == 'ON'
    return selected


def source_signature(source):
    git = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    revision = git.stdout.strip() if git.returncode == 0 else None
    digest = hashlib.sha256()
    if revision:
        names = subprocess.check_output(['git', '-C', str(source), 'ls-files', '--cached', '--others',
                                         '--exclude-standard', '-z']).decode().split('\0')
    else:
        names = [str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()]
    for name in sorted(set(names)):
        if not name or set(Path(name).parts) & {'build', '.git', '.cache', '.serena'}:
            continue
        path = source / name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.is_file() else b'<removed>')
    return {'source': str(source), 'revision': revision, 'content': digest.hexdigest()}


def toolchain_signature(context=None):
    context = context or {}
    result = {}
    for name, command in [('cc', context.get('CMAKE_C_COMPILER', os.environ.get('CC', 'cc'))), ('cxx', context.get('CMAKE_CXX_COMPILER', os.environ.get('CXX', 'c++'))),
                          ('cmake', 'cmake'), ('ninja', 'ninja')]:
        args = [command] if shutil.which(command) else shlex.split(command)
        path = shutil.which(args[0])
        version = subprocess.check_output([*args, '--version'], text=True).strip()
        result[name] = {'command': args, 'path': str(Path(path).resolve()) if path else None, 'version': version}
    result['bundle_version'] = (Path(__file__).parent / 'VERSION').read_text().strip()
    result['environment'] = {key: value for key, value in sorted(os.environ.items())
                             if key in {'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'Qt6_DIR',
                                        'CMAKE_PREFIX_PATH', 'CMAKE_TOOLCHAIN_FILE', 'PKG_CONFIG_PATH',
                                        'HOLONIGHT_EXTERNAL_PREFIX'}}
    result['preset_context'] = context
    toolchain = context.get('CMAKE_TOOLCHAIN_FILE', os.environ.get('CMAKE_TOOLCHAIN_FILE'))
    if toolchain:
        result['toolchain_content'] = hashlib.sha256(Path(toolchain).read_bytes()).hexdigest()
    return result


def prepare_external(config, context=None, features=None):
    context = context or {}
    sources = [dep for dep in config.get('external_sources', []) if os.environ.get(dep['source_variable'])]
    if sources and config.get('external_dependencies'):
        active = {item['id'] for item in external_requirements(config, features=features)}
        sources = [dep for dep in sources if dep.get('id', dep['module']) in active]
    if sources and os.environ.get('HOLONIGHT_EXTERNAL_PREFIX'):
        raise RuntimeError('Choose supplied external sources or HOLONIGHT_EXTERNAL_PREFIX with installed packages; '
                           'conflicting external providers are not prepared implicitly.')
    if not sources:
        return
    location = ROOT / 'build/external/prefix'
    # Probe the system/toolchain requirements first, excluding only explicitly supplied external sources.
    provided = {dep['module'] for dep in sources}
    prerequisites = dict(config, external_dependencies=[item for item in config.get('external_dependencies', [])
                                                       if item['id'] not in provided])
    external = check_external(prerequisites, cmake_options=context)
    state_path = ROOT / 'build/external/provider-state.json'
    try:
        previous = json.loads(state_path.read_text())
    except (OSError, ValueError):
        previous = {}
    state = {dep['module']: {**source_signature(dependency_source(dep)), 'options': dep.get('options', []),
                            'toolchain': toolchain_signature(context), 'external': external} for dep in sources}
    artifacts = location.exists() or any((ROOT / 'build/external').glob('**/CMakeCache.txt'))
    if (previous or artifacts) and previous != state:
        number = 1
        while (ROOT / f'build/external.previous-{number}').exists():
            number += 1
        (ROOT / 'build/external').rename(ROOT / f'build/external.previous-{number}')
        previous = {}
    for dep in sources:
        if previous.get(dep['module']) == state[dep['module']]:
            try:
                packages({'dependencies': [dep]}, location)
                continue
            except RuntimeError:
                pass
        build = ROOT / 'build/external' / dep['module']
        run(['cmake', '-S', dependency_source(dep), '-B', build, '-G', 'Ninja',
             '-DCMAKE_BUILD_TYPE=Debug', '-DBUILD_TESTING=OFF', '-DCMAKE_INSTALL_LIBDIR=lib',
             f'-DCMAKE_INSTALL_PREFIX={location}', *[f'-D{key}={value}' for key, value in context.items()],
             *dep.get('options', [])], env=discovery_environment())
        run(['cmake', '--build', build, '--parallel', os.environ.get('JOBS', '2')])
        run(['cmake', '--install', build])
    atomic_json(state_path, state)
    os.environ['HOLONIGHT_EXTERNAL_PREFIX'] = str(location)


def provider_options(source, config):
    text = (source / 'CMakeLists.txt').read_text()
    declared = set(re.findall(r'option\s*\(\s*(\w+)', text, re.I))
    if re.search(r'include\s*\(\s*CTest\s*\)', text, re.I):
        declared.add('BUILD_TESTING')
    values = {'BUILD_TESTS': False, 'BUILD_TESTING': False, 'BUILD_DEMO': False,
              'BUILD_CONTROLS_GALLERY': False, 'BUILD_WAYLAND': config.get('wayland', False),
              'BUILD_COMPOSITOR_WAYLAND': config.get('wayland', False)}
    return [f'-D{key}={"ON" if enabled else "OFF"}' for key, enabled in values.items() if key in declared]


def prepare(config, preset='debug'):
    context = build_context(preset)
    # This is the only operation that prepares supplied local provider sources.
    prepare_external(config, context, selected_features(config, preset))
    external = check_external(config, features=selected_features(config, preset), cmake_options=context,
                              evidence=ROOT / 'build/deps/external-state.json')
    location = prefix()
    if not config.get('dependencies'):
        return
    if os.environ.get('HOLONIGHT_DEPENDENCY_PREFIX'):
        packages(config, location)
        return
    sources = [(dep, dependency_source(dep)) for dep in config['dependencies']]
    state_path = ROOT / 'build/deps/provider-state.json'
    try:
        old_state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        old_state = {}
    state = {}
    toolchain = toolchain_signature(context)
    build_type = os.environ.get('HOLONIGHT_PROVIDER_BUILD_TYPE', 'Debug')
    for dep, source in sources:
        state[dep['module']] = {**source_signature(source), 'prefix': str(location),
                               'options': [*provider_options(source / dep.get('cmake_subdirectory', ''), config), *dep.get('options', [])],
                               'cmake_subdirectory': dep.get('cmake_subdirectory', ''), 'wayland': config.get('wayland', False),
                               'build_type': build_type, 'toolchain': toolchain, 'external': external}
    artifacts = location.exists() or any((ROOT / 'build/deps').glob('**/CMakeCache.txt'))
    if (old_state or artifacts) and old_state != state:
        # Preserve incompatible artifacts for inspection, but never reuse their caches or install trees.
        directory = ROOT / 'build/deps'
        number = 1
        while (ROOT / f'build/deps.previous-{number}').exists():
            number += 1
        directory.rename(ROOT / f'build/deps.previous-{number}')
        old_state = {}
    revision_lines = []
    for dep, source in sources:
        signature = state[dep['module']]
        revision_lines.append(f'{dep["module"]}\t{source}\t{signature["revision"] or "unversioned"}')
        try:
            packages({'dependencies': [dep]}, location)
            installed = True
        except RuntimeError:
            installed = False
        if installed and old_state.get(dep['module']) == signature:
            print(f'{dep["module"]}: compatible source, toolchain and installed package are current')
            continue
        build = ROOT / 'build/deps' / dep['module']
        args = ['cmake', '-S', source / dep.get('cmake_subdirectory', ''), '-B', build, '-G', 'Ninja', f'-DCMAKE_BUILD_TYPE={build_type}',
                f'-DCMAKE_INSTALL_PREFIX={location}', '-DCMAKE_INSTALL_LIBDIR=lib',
                f'-DCMAKE_PREFIX_PATH={cmake_prefixes(location)}', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                *provider_options(source / dep.get('cmake_subdirectory', ''), config)]
        if os.environ.get('CMAKE_TOOLCHAIN_FILE'):
            args.append('-DCMAKE_TOOLCHAIN_FILE=' + os.environ['CMAKE_TOOLCHAIN_FILE'])
        args.extend(f'-D{key}={value}' for key, value in context.items())
        args.extend(dep.get('options', []))
        env = discovery_environment(location)
        run(args, env=env)
        run(['cmake', '--build', build, '--parallel', os.environ.get('JOBS', '2')], env=env)
        run(['cmake', '--install', build], env=env)
    packages(config, location)
    atomic_json(state_path, state)
    atomic_json(ROOT / 'build/deps/external-state.json', external)
    (ROOT / 'build/deps/provider-revisions.tsv').write_text('\n'.join(revision_lines) + '\n')


def configure(config, preset):
    packages(config, prefix())
    features = selected_features(config, preset)
    external = check_external(config, scopes=('build', 'tool', 'test') if preset == 'test' else ('build', 'tool'),
                              features=features, cmake_options=build_context(preset))
    state = {'toolchain': toolchain_signature(build_context(preset)), 'external': external,
             'providers': {package: {'path': str(path), 'content': hashlib.sha256(
                 b''.join(file.name.encode() + file.read_bytes() for file in sorted(path.glob('*.cmake')))).hexdigest()}
                 for package, path in packages(config, prefix()).items()},
             'prefixes': cmake_prefixes(prefix()),
             'presets': (ROOT / 'CMakePresets.json').read_text() if (ROOT / 'CMakePresets.json').exists() else None}
    directory = ROOT / 'build' / preset
    state_path = directory / 'dependency-state.json'
    try:
        previous = json.loads(state_path.read_text())
    except (OSError, ValueError):
        previous = None
    if (directory / 'CMakeCache.txt').exists() and previous != state:
        number = 1
        while (ROOT / 'build' / f'{preset}.previous-{number}').exists():
            number += 1
        directory.rename(ROOT / 'build' / f'{preset}.previous-{number}')
    args = ['cmake', '--preset', preset, f'-DCMAKE_PREFIX_PATH={cmake_prefixes(prefix())}']
    if config.get('dependencies'):
        args.append(f'-DHOLONIGHT_DEPENDENCY_PREFIX={prefix()}')
    if config.get('qml'):
        args.append('-DQML_IMPORT_PATH=' + ';'.join(str(p / 'lib/qt6/qml') for p in (prefix(), external_prefix()) if p))
    args.extend(f'-D{key}={"ON" if enabled else "OFF"}' for key, enabled in features.items())
    if os.environ.get('QMLLINT'):
        args.append('-DQMLLINT=' + os.environ['QMLLINT'])
    if config.get('module') == 'holonight-qt':
        for tool in ('QML', 'QMLLINT'):
            if os.environ.get(tool):
                args.append(f'-DHOLONIGHT_{tool}_EXECUTABLE=' + os.environ[tool])
    args += [f'-D{package}_DIR={path}' for package, path in packages(config, prefix()).items()]
    if external_prefix() and config.get('dependencies'):
        args.append(f'-DHOLONIGHT_EXTERNAL_PREFIX={external_prefix()}')
    run(args, env=discovery_environment(prefix()))
    atomic_json(state_path, state)
    atomic_json(directory / 'external-state.json', external)
    refresh(config, preset)


def refresh(config, preset='test'):
    entries, report = merge(ROOT)
    if entries:
        # Compiler commands remain intact. clangd removes unsupported flags through .clangd.
        atomic_json(ROOT / 'compile_commands.json', entries)
        atomic_json(ROOT / '.cache/tooling/coverage.json', report)
    elif config.get('cpp'):
        raise RuntimeError('No valid compile commands; previous database preserved. Run task configure PRESET=test.')
    if config.get('qml'):
        build = (ROOT / 'build' / preset).resolve()
        imports = [build, build / 'qml', configured_prefix(preset) / 'lib/qt6/qml']
        if external_prefix():
            imports.append(external_prefix() / 'lib/qt6/qml')
        cache = build / 'CMakeCache.txt'
        if cache.exists():
            match = re.search(r'^QML_IMPORT_PATH:(?:STRING|PATH)=(.*)$', cache.read_text(), re.M)
            if match:
                imports.extend(Path(p) for p in match[1].split(';') if p)
        imports += [p.parent for p in build.rglob('qmldir')]
        text = '[General]\nno-cmake-calls=true\nbuildDir=' + str(build) + '\nimportPaths=' + ','.join(map(str, dict.fromkeys(imports))) + '\n'
        local = ROOT / '.cache/tooling/qmlls/.qmlls.ini'
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(text)
        # qmlls reads the root ini. .git/info/exclude cannot override a tracked file:
        # keep the tracked portable root config, pass resolved paths via the wrapper.
        atomic_json(ROOT / '.cache/tooling/qml-paths.json', {'build': str(build), 'imports': list(map(str, dict.fromkeys(imports))), 'preset': preset})
        local_project = ROOT / '.serena/project.local.yml'
        overrides = {}
        if local_project.exists():
            try:
                overrides = json.loads(local_project.read_text())
            except ValueError:
                print('Existing YAML project.local.yml preserved; use tooling:qmlls or configure ls_base_cmd manually.')
                overrides = None
        if overrides is not None:
            qml_settings = overrides.setdefault('ls_specific_settings', {}).setdefault('qml', {})
            qml_settings['ls_base_cmd'] = [sys.executable, str(ROOT / 'tooling/workflow.py'), 'qmlls']
            atomic_json(local_project, overrides)
    print(f'Refresh: {len(entries)} compile commands; editor build build/{preset}')


def owned_files(suffixes):
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    return [ROOT / p for p in files if p and Path(p).suffix in suffixes
            and not set(Path(p).parts) & {'tooling', 'third_party', 'vendor', 'docs', '.serena'}]


def qt_tool(name, preset='test'):
    override = os.environ.get(name.upper())
    if override:
        return override
    cache = ROOT / 'build' / preset / 'CMakeCache.txt'
    qt_dir = os.environ.get('Qt6_DIR', '')
    if cache.exists():
        match = re.search(r'^Qt6_DIR:PATH=(.*)$', cache.read_text(), re.M)
        if match:
            qt_dir = match[1]
    if qt_dir:
        qt_prefix = Path(qt_dir).resolve().parents[2]
        for directory in [qt_prefix / 'bin', qt_prefix / 'lib/qt6/bin', qt_prefix / 'libexec']:
            if (directory / name).is_file() and os.access(directory / name, os.X_OK):
                return str(directory / name)
    raise RuntimeError(f'Cannot resolve {name} from configured Qt. Configure build/{preset} or set {name.upper()}.')


def tidy(config, scope):
    refresh(config)
    entries = json.loads((ROOT / 'compile_commands.json').read_text())
    clang_entries = []
    for entry in entries:
        args = entry.get('arguments') or shlex.split(entry['command'])
        args = [a for a in args if a not in {'-mno-direct-extern-access', '-fno-keep-inline-dllexport'}]
        clang_entries.append(dict(directory=entry['directory'], file=entry['file'], arguments=args))
    target = ROOT / '.cache/tooling/clang'
    atomic_json(target / 'compile_commands.json', clang_entries)
    sources = set(owned_files({'.cpp', '.cc', '.cxx', '.c'}))
    selected = [e for e in entries if Path(e['file']) in sources]
    for entry in selected:
        path = Path(entry['file'])
        is_test = 'tests' in path.relative_to(ROOT).parts
        if scope == 'src' and is_test or scope == 'tests' and not is_test:
            continue
        tidy_config = ROOT / 'tests/.clang-tidy' if is_test and (ROOT / 'tests/.clang-tidy').exists() else ROOT / '.clang-tidy'
        run([os.environ.get('CLANG_TIDY', 'clang-tidy'), path, '-p', target,
             f'--config-file={tidy_config}'])
    uncovered = sources - {Path(e['file']) for e in entries}
    if uncovered:
        raise RuntimeError('No compile command for: ' + ', '.join(str(p.relative_to(ROOT)) for p in sorted(uncovered)))


def metadata(config, preset):
    build = ROOT / 'build' / preset
    artifacts = [p for p in build.rglob('qmldir') if 'tests' not in p.relative_to(build).parts and 'runtime-qml' not in p.relative_to(build).parts]
    if not artifacts:
        raise RuntimeError(f'No generated qmldir in {build}; run task build PRESET={preset}.')
    for uri in config.get('qml_modules', []):
        matching = [p for p in artifacts if f'module {uri}\n' in p.read_text()]
        if not matching:
            raise RuntimeError(f'Missing generated module {uri} in {build}')
        for qmldir in matching:
            for name in re.findall(r'^typeinfo\s+(\S+)', qmldir.read_text(), re.M):
                path = qmldir.parent / name
                if not path.is_file() or not re.search(r'\bModule\s*\{', path.read_text()):
                    raise RuntimeError(f'Missing or empty QML type metadata: {path}')


def doctor(config):
    errors = []
    names = ['python3', 'task', 'serena'] + config.get('required_tools', [])
    if (ROOT / 'CMakeLists.txt').is_file():
        names += ['cmake', 'ninja']
    if 'cpp' in config.get('languages', []):
        names += ['clangd', 'clang-format', 'clang-tidy']
    if 'bash' in config.get('languages', []):
        names += ['node', 'bash-language-server', 'shellcheck']
    for name in names:
        found = shutil.which(name)
        if not found and name in {'bash-language-server', 'shellcheck'}:
            managed = Path.home() / '.serena/language_servers/static/BashLanguageServer'
            matches = [p for p in managed.glob('**/' + name) if p.is_file() and os.access(p, os.X_OK)]
            found = str(matches[0]) + ' (Serena managed)' if matches else None
        print(f'{name}: {found or "MISSING"}')
        if not found:
            errors.append(name)
    for variant in ['test', 'debug', 'release']:
        print(f'build/{variant}: {"configured" if (ROOT / "build" / variant / "CMakeCache.txt").exists() else "missing; task configure PRESET=" + variant}')
    try:
        packages(config, configured_prefix())
    except RuntimeError as exc:
        errors.append(str(exc))
    entries, report = merge(ROOT)
    print(json.dumps({k: v for k, v in report.items() if k != 'origins'}, indent=2))
    if config.get('qml'):
        for name in ['qmlls', 'qmllint', 'qmlformat']:
            try:
                print(f'{name}: {qt_tool(name)}')
            except RuntimeError as exc:
                errors.append(str(exc))
        for uri in ['Holonight.Core', 'Holonight.Controls']:
            path = configured_prefix() / 'lib/qt6/qml' / uri.replace('.', '/') / 'qmldir'
            if config['module'] != 'holonight-qt' and not path.is_file():
                errors.append(f'Missing import {uri}: task deps, then task build PRESET=test')
    for error in errors:
        print('ACTION:', error)
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command')
    parser.add_argument('--preset', default='debug')
    parser.add_argument('--tool', choices=['qmlls', 'qmllint', 'qmlformat', 'qml'])
    parser.add_argument('--scope', default='all', choices=['all', 'src', 'tests'])
    args = parser.parse_args()
    config = settings()
    command = args.command
    if command == 'qt-tool':
        if not args.tool:
            parser.error('--tool is required for qt-tool')
        print(qt_tool(args.tool, args.preset))
    elif command == 'deps':
        prepare(config, args.preset)
    elif command == 'configure':
        configure(config, args.preset)
    elif command in {'build', 'test'}:
        preset = 'test' if command == 'test' else args.preset
        configure(config, preset)
        run(['cmake', '--build', '--preset', preset, '--parallel', os.environ.get('JOBS', '2')])
        refresh(config, preset)
        if command == 'test':
            run(config.get('test_command_prefix', []) + ['ctest', '--preset', 'test'], env=dict(os.environ, QT_QPA_PLATFORM='offscreen'))
    elif command == 'refresh':
        refresh(config, args.preset)
    elif command == 'doctor':
        sys.exit(doctor(config))
    elif command in {'format', 'format-check'}:
        for path in owned_files({'.cpp', '.cc', '.cxx', '.h', '.hpp', '.c'}):
            run([os.environ.get('CLANG_FORMAT', 'clang-format'), *(['--dry-run', '--Werror'] if command.endswith('check') else ['-i']), path])
    elif command == 'tidy':
        tidy(config, args.scope)
    elif command == 'qmltypes-check':
        metadata(config, args.preset)
    elif command == 'qmlls':
        cache = ROOT / '.cache/tooling/qml-paths.json'
        if not cache.exists():
            refresh(config, 'test')
        paths = json.loads(cache.read_text())
        env = dict(os.environ, QML_IMPORT_PATH=os.pathsep.join(paths['imports']), QMLLS_NO_CMAKE_CALLS='1')
        command = [qt_tool('qmlls', paths.get('preset', 'test')), '--ignore-settings', '--no-cmake-calls', '--build-dir', paths['build']]
        for path in paths['imports']:
            command.extend(['-I', path])
        run(command, env=env)
    else:
        parser.error(f'Unknown capability: {command}')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        sys.exit(str(exc))
