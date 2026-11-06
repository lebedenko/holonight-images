# SPDX-License-Identifier: GPL-3.0-or-later
"""Caller-owned scenario and evidence expectations for private regression suites."""
CANCELLATION = ['before-transfer', 'blocked-input', 'await-response', 'partial-control',
                'partial-pixels', 'term-resistant-descendant', 'eof-race', 'malformed-race',
                'timeout-race', 'manager-failure', 'exhausted-budget']
LINKED_INVALID = ['external', 'encoded', 'absolute', 'traversal', 'query', 'fragment',
                  'reserved', 'prefix', 'staging-prefix', 'missing', 'symlink',
                  'intermediate-symlink', 'count', 'long-path', 'xml-base', 'css', 'entity',
                  'animated-reference']
CAPSULE = ['same-directory', 'descendant', 'traversal', 'absolute', 'file-url', 'network',
           'symlink', 'external-xml']


def scenarios(suite, options):
    if suite == 'gif-attribution':
        from gif_attribution import expectations
        return expectations()[0]
    if suite == 'cancellation':
        return CANCELLATION + ([] if options['focused'] else [
            f'{backend}-{loaded}-{phase}-{n}' for backend in ('qt', 'glycin')
            for loaded in (False, True) for phase in ('dispatched', 'before-result') for n in range(3)])
    if suite == 'capture':
        return [f'{backend}-{kind}-{mutation}' for kind in ('png', 'jpeg', 'svg')
                for mutation in ('replace', 'remove') for backend in ('qt', 'glycin')] + [
                    f'probe-limit-{n}' for n in (1, 0, -1, 256 * 1024 * 1024 + 1)]
    if suite == 'linked':
        return ['cpp-acquisition', 'untrusted-manifest', 'unsupported-openat2'] + ([] if options['focused'] else
            [f'{case}-{mutation}' for case in ('same', 'descendant', 'repeated')
             for mutation in ('replace', 'remove')] + ['reject-' + name for name in LINKED_INVALID] +
            ['barrier-' + name for name in ('main-change', 'main-replace', 'main-delete', 'base-rename', 'cancel')] +
            ['content-' + name for name in ('nested-svg', 'invalid-raster', 'animated-raster')] +
            ['embedded-and-local-fragment'])
    if suite == 'check':
        names = ['snapshot'] + ['protocol-' + name for name in ('crash', 'control', 'oversize', 'stride', 'hang')]
        names += ['filesystem-network-isolation']
        for backend in ('qt', 'glycin'):
            names += [backend + '-color-' + name for name in ('rgba16.png', 'invalid-icc.png')]
            names += [backend + '-structured-exif', backend + '-gif-delays-pixels-restart']
            names += [backend + '-capsule-' + name for name in CAPSULE]
        return [name for name in names if options['filter'] in name]
    raise ValueError('unknown suite: ' + suite)


def requirements(suite, options):
    if suite == 'gif-attribution':
        from gif_attribution import expectations
        return expectations()[1]
    output = {}
    for name in scenarios(suite, options):
        count, artifacts = 1, []
        if suite == 'cancellation':
            count = 2 if name.startswith(('qt-', 'glycin-')) else 1
            if count == 2:
                artifacts = ['captured.png']
            elif name == 'blocked-input':
                artifacts = ['blocked-input.input']
        elif suite == 'capture':
            count = 0 if name.startswith('probe-limit-') else 1
            if count:
                _, kind, mutation = name.split('-')
                artifacts = [name + '.rgba', kind + '-expected.rgba', kind + '-' + mutation + '-captured.bin']
        elif suite == 'linked':
            count = 0 if name in ('cpp-acquisition', 'untrusted-manifest', 'unsupported-openat2') else 1
            if name in [f'{case}-{mutation}' for case in ('same', 'descendant', 'repeated') for mutation in ('replace', 'remove')] or name == 'embedded-and-local-fragment':
                count = 7
                artifacts = [name + '/discovery.trace', name + '/expected.rgba']
                artifacts += [f'{name}/{backend}-{n}.{ext}' for backend in ('qt', 'glycin') for n in range(3) for ext in ('trace', 'rgba')]
            elif count:
                artifacts = [name + '/discovery.trace']
                if name.startswith('content-'):
                    count = 3
                    artifacts += [name + '/' + backend + '.trace' for backend in ('qt', 'glycin')]
            elif name == 'unsupported-openat2':
                artifacts = [name + '/enosys.trace']
        elif suite == 'check':
            count = 0 if name == 'snapshot' else 1
        if suite == 'linked':
            if count:
                artifacts.append(name + '/input.svg')
            if count == 7 or name.startswith('content-') or name == 'barrier-base-rename':
                artifacts.append(name + '/captured/main.svg')
                if name != 'embedded-and-local-fragment':
                    resources = ['child/pixel.png'] if name.startswith('descendant-') else ['pixel.png']
                    if name.startswith('repeated-'):
                        resources += ['child/pixel.png']
                    artifacts += [name + '/captured/' + resource for resource in resources]
        artifacts += [path + '.json' for path in artifacts if path.endswith('.trace') and not path.endswith('/enosys.trace')] if suite == 'linked' else []
        output[name] = dict(artifacts=artifacts, min_scopes=count, scopes=[])
        if suite == 'cancellation' and name in ('manager-failure', 'exhausted-budget'):
            output[name]['cleanup_failure'] = True
    return output
