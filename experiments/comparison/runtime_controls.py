# SPDX-License-Identifier: GPL-3.0-or-later
"""Invocation-local native activation controls; no host configuration writes."""
import json
from pathlib import Path
import shutil

from harness import Worker
from runtime_bundle import host_environment
from runtime_evidence import require

CHANNELS = ['path', 'preload', 'audit', 'library', 'qt-plugin', 'qt-conf',
            'glycin-data', 'xdg-data-home', 'xdg-data-dirs', 'xdg-config-home',
            'xdg-config-dirs', 'host-file', 'host-network']
ENVIRONMENT = ['PATH', 'LD_PRELOAD', 'LD_AUDIT', 'LD_LIBRARY_PATH', 'QT_PLUGIN_PATH',
               'QT_QPA_PLATFORM_PLUGIN_PATH', 'GLYCIN_DATA_DIR', 'GLYCIN_DISABLE_SANDBOX',
               'XDG_DATA_HOME', 'XDG_DATA_DIRS', 'XDG_CONFIG_HOME', 'XDG_CONFIG_DIRS']


def expect(channel, response, stderr):
    checks = {
        'path': response.get('path_token') == 'HN_PATH_ACTIVATED',
        'preload': 'HN_PRELOAD_ACTIVATED' in stderr,
        'audit': 'HN_AUDIT_ACTIVATED' in stderr,
        'library': response.get('library_token') == 'HN_LIBRARY_ACTIVATED',
        'qt-plugin': response.get('plugin_pixel') == [31, 79, 127, 255],
        'qt-conf': response.get('plugin_pixel') == [31, 79, 127, 255],
        'glycin-data': response.get('glycin_loader') == '/HN_GLYCIN_DATA',
        'xdg-data-home': response.get('glycin_loader') == '/HN_GLYCIN_HOME',
        'xdg-data-dirs': response.get('glycin_loader') == '/HN_GLYCIN_DIRS',
        'xdg-config-home': response.get('configuration_token') == 'HN_CONFIG_HOME',
        'xdg-config-dirs': response.get('configuration_token') == 'HN_CONFIG_DIRS',
        'host-file': response.get('host_file') == 'HN_HOST_FILE',
        'host-network': response.get('network_reachable') is True,
    }
    require(checks[channel], 'control did not activate: ' + channel)


class Controls:
    def __init__(self, build, root):
        self.root = root / 'controls'
        self.root.mkdir()
        self.binary = build / 'runtime-diagnostic'
        for name in ('path', 'library', 'plugins/imageformats', 'adjacent', 'glycin-data',
                     'xdg-data-home', 'xdg-data-dirs', 'xdg-config-home', 'xdg-config-dirs'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        for source, target in [('hn-runtime-marker', 'path/hn-runtime-marker'),
                               ('libholonight_runtime_control_7e40.so', 'library/libholonight_runtime_control_7e40.so'),
                               ('libruntime-plugin.so', 'plugins/imageformats/libruntime-plugin.so'),
                               ('libruntime-preload.so', 'preload.so'), ('libruntime-audit.so', 'audit.so'),
                               ('runtime-diagnostic', 'adjacent/runtime-diagnostic')]:
            shutil.copyfile(build / source, self.root / target)
            (self.root / target).chmod(0o755)
        (self.root / 'adjacent/qt.conf').write_text('[Paths]\nPlugins=' + str(self.root / 'plugins') + '\n')
        for name, token in [('glycin-data', 'DATA'), ('xdg-data-home', 'HOME'), ('xdg-data-dirs', 'DIRS')]:
            path = self.root / name / 'glycin-loaders/2+/conf.d'
            path.mkdir(parents=True)
            (path / 'control.conf').write_text('[loader:image/x-holonight-runtime-control]\nExec=/HN_GLYCIN_' + token + '\n')
        for name, token in [('xdg-config-home', 'HOME'), ('xdg-config-dirs', 'DIRS')]:
            (self.root / name / 'holonight-runtime-control.conf').write_text('HN_CONFIG_' + token)
        (self.root / 'host-file').write_text('HN_HOST_FILE')

    def environment(self, channel, broken=False):
        env = host_environment()
        env.update(HOME='/nonexistent', XDG_DATA_HOME='/nonexistent', XDG_DATA_DIRS='/nonexistent',
                   XDG_CONFIG_HOME='/nonexistent', XDG_CONFIG_DIRS='/nonexistent')
        values = {'path': ('PATH', self.root / 'path'), 'preload': ('LD_PRELOAD', self.root / 'preload.so'),
                  'audit': ('LD_AUDIT', self.root / 'audit.so'), 'library': ('LD_LIBRARY_PATH', self.root / 'library'),
                  'qt-plugin': ('QT_PLUGIN_PATH', self.root / 'plugins'),
                  'glycin-data': ('GLYCIN_DATA_DIR', self.root / 'glycin-data'),
                  'xdg-data-home': ('XDG_DATA_HOME', self.root / 'xdg-data-home'),
                  'xdg-data-dirs': ('XDG_DATA_DIRS', self.root / 'xdg-data-dirs'),
                  'xdg-config-home': ('XDG_CONFIG_HOME', self.root / 'xdg-config-home'),
                  'xdg-config-dirs': ('XDG_CONFIG_DIRS', self.root / 'xdg-config-dirs')}
        if channel in values:
            key, value = values[channel]
            env[key] = '/nonexistent' if broken else str(value)
        return env

    def run(self, record, channel, *, broken=False, port=None):
        binary = self.root / 'adjacent/runtime-diagnostic' if channel == 'qt-conf' and not broken else self.binary
        env = self.environment(channel, broken)
        arguments = []
        if channel in ('host-file', 'host-network'):
            arguments = [str(self.root / ('missing-file' if broken else 'host-file'))]
        if channel == 'host-network':
            arguments += [str(port)] if not broken else ['0']
        worker = Worker(binary, isolated=False, environment=env, arguments=arguments)
        try:
            response = worker.request('diagnostic')
            record.update(response=response, environment=env, binary=str(binary))
        finally:
            record['stderr'] = worker.close()
            record['cleanup'] = worker.cleanup
        (self.root.parent / (record['name'] + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        if broken:
            try:
                expect(channel, response, record['stderr'])
            except ValueError as error:
                record['expected_rejection'] = str(error)
            else:
                raise ValueError('broken control was accepted: ' + channel)
        else:
            expect(channel, response, record['stderr'])

    def poisoned(self):
        result = {}
        for channel in CHANNELS:
            result.update({key: value for key, value in self.environment(channel).items()
                           if key in ENVIRONMENT and value != '/nonexistent' and value != '/usr/bin'})
        result.update(QT_QPA_PLATFORM_PLUGIN_PATH=str(self.root / 'plugins'), GLYCIN_DISABLE_SANDBOX='1')
        return result
