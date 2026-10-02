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

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT, **kwargs)


def settings():
    return json.loads((ROOT / 'tooling/module.json').read_text())


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


def packages(config, location):
    result = {}
    for dep in config['dependencies']:
        package = dep['package']
        candidates = sorted(location.glob(f'lib*/cmake/{package}/{package}Config.cmake'))
        candidates += sorted(location.glob(f'share/{package}/cmake/{package}Config.cmake'))
        if not candidates:
            raise RuntimeError(f'Missing {package} in {location}. Run task deps with local source overrides, '
                               'or supply HOLONIGHT_DEPENDENCY_PREFIX containing all providers.')
        result[package] = candidates[0].parent
    return result


def dependency_source(dep):
    key = dep['source_variable']
    source = Path(os.environ.get(key, ROOT.parent / dep['module'])).resolve()
    if not (source / 'CMakeLists.txt').is_file():
        raise RuntimeError(f'Missing {dep["module"]} source: {source}. Set {key} to a local checkout, '
                           'or supply HOLONIGHT_DEPENDENCY_PREFIX. Sources are never downloaded.')
    return source


def prepare(config):
    location = prefix()
    if not config['dependencies']:
        return
    if os.environ.get('HOLONIGHT_DEPENDENCY_PREFIX'):
        packages(config, location)
        return
    # Preflight every source before doing any build.
    sources = [(dep, dependency_source(dep)) for dep in config['dependencies']]
    state_path = ROOT / 'build/deps/provider-state.json'
    try:
        old_state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        old_state = {}
    state = {}
    revision_lines = []
    for dep, source in sources:
        git = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True)
        revision = git.stdout.strip() if git.returncode == 0 else None
        dirty = subprocess.run(['git', '-C', str(source), 'diff', '--no-ext-diff', 'HEAD'], capture_output=True).stdout if revision else b''
        if revision:
            untracked = subprocess.run(['git', '-C', str(source), 'ls-files', '--others', '--exclude-standard', '-z'], capture_output=True, text=True).stdout
            for name in sorted(p for p in untracked.split('\0') if p):
                file = source / name
                if file.is_file() and not set(file.relative_to(source).parts) & {'build', '.cache', '.serena', 'docs'}:
                    dirty += name.encode() + hashlib.sha256(file.read_bytes()).digest()
        signature = {'source': str(source), 'revision': revision, 'dirty': hashlib.sha256(dirty).hexdigest(),
                     'prefix': str(location), 'options': dep.get('options', []), 'wayland': config.get('wayland', False)}
        revision_lines.append(f'{dep["module"]}\t{source}\t{revision or "unversioned"}')
        state[dep['module']] = signature
        try:
            packages({'dependencies': [dep]}, location)
            installed = True
        except RuntimeError:
            installed = False
        if revision and installed and old_state.get(dep['module']) == signature:
            print(f'{dep["module"]}: source revision and installed package are current')
            continue
        build = ROOT / 'build/deps' / dep['module']
        args = ['cmake', '-S', source, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Debug',
                f'-DCMAKE_INSTALL_PREFIX={location}', '-DCMAKE_INSTALL_LIBDIR=lib',
                f'-DCMAKE_PREFIX_PATH={location}', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                '-DBUILD_TESTS=OFF', '-DBUILD_TESTING=OFF', '-DBUILD_DEMO=OFF', '-DBUILD_CONTROLS_GALLERY=OFF',
                f'-DBUILD_WAYLAND={"ON" if config.get("wayland") else "OFF"}']
        args.extend(dep.get('options', []))
        run(args)
        run(['cmake', '--build', build, '--parallel', os.environ.get('JOBS', '2')])
        run(['cmake', '--install', build])
    packages(config, location)
    atomic_json(state_path, state)
    (ROOT / 'build/deps/provider-revisions.tsv').write_text('\n'.join(revision_lines) + '\n')


def configure(config, preset):
    prepare(config)
    args = ['cmake', '--preset', preset, f'-DCMAKE_PREFIX_PATH={prefix()}',
            f'-DQML_IMPORT_PATH={prefix() / "lib/qt6/qml"}']
    if os.environ.get('QMLLINT'):
        args.append('-DQMLLINT=' + os.environ['QMLLINT'])
    if config.get('module') == 'holonight-qt':
        for tool in ('QML', 'QMLLINT'):
            if os.environ.get(tool):
                args.append(f'-DHOLONIGHT_{tool}_EXECUTABLE=' + os.environ[tool])
    args += [f'-D{package}_DIR={path}' for package, path in packages(config, prefix()).items()]
    run(args)
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
        prepare(config)
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
