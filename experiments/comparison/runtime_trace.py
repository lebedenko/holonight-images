# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured strace evidence for the private comparison acceptance runner."""
import ast
import posixpath
import re


PATH_CALLS = {
    'open': (0,), 'openat': (1,), 'openat2': (1,), 'access': (0,),
    'faccessat': (1,), 'faccessat2': (1,), 'stat': (0,), 'lstat': (0,),
    'newfstatat': (1,), 'statx': (1,), 'readlink': (0,), 'readlinkat': (1,),
    'unlink': (0,), 'unlinkat': (1,), 'mkdir': (0,), 'mkdirat': (1,),
    'rmdir': (0,), 'rename': (0, 1), 'renameat': (1, 3),
    'renameat2': (1, 3), 'link': (0, 1), 'linkat': (1, 3),
    'chdir': (0,), 'chroot': (0,), 'pivot_root': (0, 1),
    'execve': (0,), 'execveat': (1,), 'chmod': (0,), 'truncate': (0,),
    'mount': (0, 1), 'umount2': (0,), 'mount_setattr': (1,),
    'symlink': (1,), 'symlinkat': (2,), 'mknod': (0,), 'mknodat': (1,),
    'utimensat': (1,), 'fchmodat': (1,), 'fchmodat2': (1,), 'fchownat': (1,),
    'chown': (0,), 'lchown': (0,), 'utime': (0,), 'utimes': (0,), 'lutimes': (0,),
    'statfs': (0,), 'statfs64': (0,), 'truncate64': (0,),
    'getxattr': (0,), 'lgetxattr': (0,), 'setxattr': (0,), 'lsetxattr': (0,),
    'listxattr': (0,), 'llistxattr': (0,), 'removexattr': (0,), 'lremovexattr': (0,),
    'name_to_handle_at': (1,), 'open_tree': (1,), 'fspick': (1,), 'move_mount': (1, 3),
    'fanotify_mark': (4,),
}
CRITICAL = {*PATH_CALLS, 'fchdir', 'clone', 'clone3', 'fork', 'vfork',
            'dup', 'dup2', 'dup3', 'fcntl', 'close', 'connect', 'open_by_handle_at', 'fsconfig'}


def arguments(text):
    output, start, depth, quoted, escaped = [], 0, 0, False, False
    for i, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ',' and depth == 0:
            output.append(text[start:i].strip())
            start = i + 1
    if quoted or depth:
        raise ValueError('unbalanced syscall arguments')
    output.append(text[start:].strip())
    return output


def string(value):
    if not value.startswith('"'):
        raise ValueError('unresolved pathname: ' + value)
    match = re.match(r'"(?:\\.|[^"\\])*"', value)
    if not match or match.end() != len(value):
        raise ValueError('truncated pathname: ' + value)
    return ast.literal_eval(value)


def analyze(text, *, cwd=None, protected=()):
    pending, states, events, exits, interrupted = {}, {}, [], [], []
    exit_groups = set()

    def inherit(parent, flags, child, parent_pid):
        return dict(fs=parent['fs'] if 'CLONE_FS' in flags else dict(parent['fs']),
                    fds=parent['fds'] if 'CLONE_FILES' in flags else dict(parent['fds']),
                    oldroot=parent['oldroot'], group=parent['group'] if 'CLONE_THREAD' in flags else child,
                    inherited_from=parent_pid)

    def state(pid):
        if pid not in states:
            creating = [(parent, record) for (parent, call), record in pending.items()
                        if call in ('clone', 'clone3', 'fork', 'vfork')]
            if len(creating) == 1:
                parent, record = creating[0]
                states[pid] = inherit(states[parent], record[1], pid, parent)
            else:
                states[pid] = dict(fs=dict(cwd=None if creating else cwd), fds={}, oldroot=None, group=pid)
        return states[pid]

    def descriptor(value, current):
        if value.startswith('AT_FDCWD'):
            decoded = re.search(r'<(/.*)>$', value)
            return decoded.group(1) if decoded else current['fs']['cwd']
        decoded = re.search(r'^\d+<(/.*?)>(?:\(deleted\))?$', value)
        if decoded:
            return decoded.group(1)
        match = re.match(r'^\d+', value)
        return current['fds'].get(int(match.group())) if match else None

    def resolve(value, base):
        path = string(value)
        if path.startswith('/'):
            return posixpath.normpath(path)
        if base is None:
            raise ValueError('relative pathname without directory state: ' + value)
        return posixpath.normpath(posixpath.join(base, path))

    for number, raw in enumerate(text.splitlines(), 1):
        match = re.match(r'\s*(?:\[pid\s+)?(\d+)\]?\s+(.*)', raw)
        if not match:
            if raw.strip():
                raise ValueError(f'unrecognized trace line {number}: {raw}')
            continue
        pid, line = int(match[1]), match[2]
        current = state(pid)
        numbered = re.match(r'\[\s*(-?\d+|\?+)\]\s*(.*)', line)
        syscall_number = int(numbered[1]) if numbered and '?' not in numbered[1] else None
        if numbered:
            line = numbered[2]
        terminal = re.match(r'\+\+\+ (?:exited with (\d+)|killed by (\w+)).*\+\+\+', line)
        if terminal:
            exits.append(dict(pid=pid, status=int(terminal[1]) if terminal[1] else None,
                              signal=terminal[2], line=number))
            for key in [key for key in pending if key[0] == pid]:
                call, first, start, original_number = pending.pop(key)
                if call in CRITICAL:
                    raise ValueError(f'incomplete critical syscall at line {start}')
                if not (terminal[2] or current['group'] in exit_groups or call in ('exit', 'exit_group')):
                    raise ValueError(f'noncritical call lacks termination proof at line {start}')
                interrupted.append(dict(pid=pid, syscall=call, syscall_number=original_number,
                                        classification='terminated-noncritical',
                                        line=start, terminal_line=number))
            continue
        if line.startswith(('--- ', 'strace:')):
            continue
        resumed = re.match(r'<\.\.\. (\w+) resumed>(.*)', line)
        if resumed:
            key = (pid, resumed[1])
            if key not in pending:
                raise ValueError(f'unmatched resumed syscall at line {number}')
            call, first, start, syscall_number = pending.pop(key)
            line = first + resumed[2]
            lines = [start, number]
        else:
            start = re.match(r'(\w+|\?\?\?)\(', line)
            if not start:
                raise ValueError(f'incomplete trace line {number}: {line}')
            call = start[1]
            if call == 'exit_group':
                exit_groups.add(current['group'])
            if call == '???':
                raise ValueError(f'unresolved syscall at line {number}')
            lines = [number]
            if '<unfinished ...>' in line:
                key = (pid, call)
                if key in pending:
                    raise ValueError('overlapping syscall')
                pending[key] = (call, line.split('<unfinished ...>')[0], number, syscall_number)
                continue
        parsed = re.match(r'\w+\((.*)\)\s+=\s+(.+)$', line)
        if not parsed:
            # exit_group has no result when the process terminates.
            if call in ('exit', 'exit_group'):
                continue
            raise ValueError(f'incomplete syscall result at line {number}')
        args, result = arguments(parsed[1]), parsed[2]
        status = re.match(r'(-?(?:0x[0-9a-fA-F]+|\d+))(?:<([^>]+)>(?:\(deleted\))?)?(?=\s|$)(?:\s+(\w+))?', result)
        if not status:
            if call in CRITICAL:
                raise ValueError(f'unresolved critical result at line {number}')
            interrupted.append(dict(pid=pid, syscall=call, line=lines[0],
                                    classification='noncritical-without-result'))
            continue
        code = int(status[1], 16 if '0x' in status[1] else 10)
        if code == -1 and call in CRITICAL and not status[3]:
            raise ValueError(f'missing critical error result at line {number}')
        event = dict(pid=pid, syscall=call, syscall_number=syscall_number, arguments=args, result=result,
                     returncode=code, errno=status[3] if code == -1 else None,
                     lines=lines, paths=[], classification='other')
        for index in PATH_CALLS.get(call, ()):
            if call == 'mount' and (args[index] == 'NULL' or not args[index].startswith('"')):
                continue
            if call == 'mount' and index == 0 and not any(flag in args[3] for flag in ('MS_BIND', 'MS_MOVE')):
                continue
            base = current['fs']['cwd']
            if call.endswith('at') or call in ('openat2', 'renameat2', 'statx', 'execveat', 'faccessat2', 'fchmodat2',
                                              'mount_setattr', 'name_to_handle_at', 'open_tree', 'fspick', 'move_mount', 'fanotify_mark'):
                base = descriptor(args[index - 1], current)
            try:
                event['paths'].append(resolve(args[index], base))
            except ValueError as error:
                raise ValueError(f'{error}; line {number}: {raw}') from error
        if call == 'open_by_handle_at' and code >= 0:
            if not status[2] or not status[2].startswith('/'):
                raise ValueError('unresolved successful open_by_handle_at')
            event['paths'].append(posixpath.normpath(status[2]))
        if call == 'fsconfig' and code >= 0 and any('FSCONFIG_SET_PATH' in arg for arg in args):
            raise ValueError('unresolved successful mount configuration path')
        if call == 'fchdir' and code >= 0:
            target = descriptor(args[0], current)
            if target is None:
                raise ValueError('unresolved fchdir')
            event['paths'].append(target)
        if call in ('execve', 'execveat'):
            event['classification'] = 'execution' if code == 0 else 'failed-execution'
        elif event['paths']:
            event['classification'] = 'path-operation' if code >= 0 else 'lookup-probe'
        elif call == 'connect':
            event['classification'] = 'network-connected' if code == 0 else 'network-failed'
        if code >= 0:
            if call in ('clone', 'clone3', 'fork', 'vfork') and code > 0:
                translated = re.search(r'/\*\s*(\d+)\s+in strace.s PID NS\s*\*/', result)
                child = int(translated[1]) if translated else code
                if child not in states:
                    states[child] = inherit(current, parsed[1], child, pid)
                elif states[child].get('inherited_from') != pid:
                    raise ValueError(f'ambiguous process inheritance at line {number}: parent={pid}, child={child}')
                event['child_pid'] = child
            elif call == 'chdir':
                current['fs']['cwd'] = event['paths'][0]
            elif call == 'fchdir':
                current['fs']['cwd'] = descriptor(args[0], current)
                if current['fs']['cwd'] is None:
                    raise ValueError('unresolved fchdir')
            elif call in ('chroot', 'pivot_root'):
                # Bwrap temporarily exposes the previous root at /oldroot. Preserve
                # directory descriptors; -yy decodes surviving descriptors after pivot.
                if call == 'pivot_root' and string(args[1]) != '.':
                    old = event['paths'][1]
                    new = event['paths'][0]
                    current['oldroot'] = '/' + posixpath.relpath(old, new)
                current['fs']['cwd'] = '/'
            elif call in ('open', 'openat', 'openat2'):
                current['fds'][code] = status[2] or event['paths'][0]
            elif call in ('dup', 'dup2', 'dup3') or (call == 'fcntl' and 'F_DUPFD' in args[1]):
                current['fds'][code] = descriptor(args[0], current)
            elif call == 'close':
                current['fds'].pop(int(re.match(r'\d+', args[0])[0]), None)
        event['canonical_paths'] = [path[len(current['oldroot']):] or '/'
                                    if current['oldroot'] and (path == current['oldroot'] or path.startswith(current['oldroot'] + '/'))
                                    else path for path in event['paths']]
        event['protected'] = [path for path in event['canonical_paths'] if any(
            path == str(tree) or path.startswith(str(tree).rstrip('/') + '/') for tree in protected)]
        events.append(event)
    if pending:
        raise ValueError('unfinished syscall records')
    for event in interrupted:
        if not any(terminal['pid'] == event['pid'] for terminal in exits):
            raise ValueError('unterminated noncritical syscall')
    return dict(events=events, exits=exits, interrupted=interrupted,
                successful_execs=[e['paths'][0] for e in events if e['classification'] == 'execution'],
                protected_operations=[e for e in events if e['protected'] and e['returncode'] >= 0])


def successful_executions(text):
    executions = analyze(text)['successful_execs']
    if not executions:
        raise ValueError('missing successful execution evidence')
    return executions


def require_trial(findings, worker, loader=None):
    executions = [e for e in findings['events'] if e['classification'] == 'execution']
    workers = [e for e in executions if e['paths'] == [worker]]
    if len(workers) != 1:
        raise ValueError('missing or duplicate worker execution')
    if findings['protected_operations']:
        raise ValueError('successful protected-path operation')
    if loader:
        loaders = [e for e in executions if e['paths'] == [loader]]
        outer = [e for e in executions if e['paths'] == ['/usr/bin/bwrap']
                 and e['lines'][0] < workers[0]['lines'][0]]
        nested = [e for e in executions if e['paths'] == ['/usr/bin/bwrap']
                  and e['lines'][0] > workers[0]['lines'][0] and e['pid'] != workers[0]['pid']]
        if not loaders or not outer or not nested:
            raise ValueError('missing successful outer/nested sandbox or loader execution')


def require_failure(findings, *, stage, kind, worker, replacement, diagnostic, load, status):
    """Four exact stage contracts; EOF, timeout and protocol errors are not proof."""
    executions = [e for e in findings['events'] if e['classification'] == 'execution']
    attempts = [e for e in findings['events'] if e['syscall'] in ('execve', 'execveat')
                and e['paths'] == [replacement]]
    workers = [e for e in executions if e['paths'] == [worker]]
    if not attempts:
        raise ValueError('missing injected execution attempt')
    attempt = attempts[-1]
    if kind == 'missing':
        if attempt['returncode'] != -1 or attempt['errno'] != 'ENOENT':
            raise ValueError('injection did not fail with ENOENT')
        if not any(token in diagnostic.lower() for token in ('no such file', 'os error 2', 'not found')):
            raise ValueError('missing ENOENT diagnostic')
    elif (attempt['classification'] != 'execution' or not any(
            e['pid'] == attempt['pid'] and e['status'] == 1 for e in findings['exits'])):
        raise ValueError('replacement did not execute and exit 1')
    if stage == 'outer':
        if workers or status not in (1, 127):
            raise ValueError('outer injection reached worker or wrong exit')
    else:
        if (not workers or not any(e['paths'] == ['/usr/bin/bwrap']
                                  and e['lines'][0] < workers[0]['lines'][0] for e in executions)
                or attempt['lines'][0] <= workers[0]['lines'][0]
                or not isinstance(load, dict) or load.get('outcome') != 'failure'
                or not load.get('error')):
            raise ValueError('wrong nested failure stage or absent structured load failure')
    return dict(stage=stage, kind=kind, attempt=attempt, diagnostic=diagnostic, launcher_status=status)
