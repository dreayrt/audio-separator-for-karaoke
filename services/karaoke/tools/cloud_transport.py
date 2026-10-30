"""SSH/SCP transport with a pinned server host key, without shelling out locally."""

import hashlib
import base64
import json
import os
from pathlib import Path
import shlex
import subprocess


class CloudTransport:
    def __init__(self, target, key, known_hosts, fingerprint=None):
        self.target = target
        self.key = str(Path(key).expanduser().resolve())
        self.known_hosts = Path(known_hosts).resolve()
        self.fingerprint = fingerprint
        self.plink = None
        if Path(self.key).suffix == '.ppk':
            local_app = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData/Local'))
            sdk = local_app / 'Google/Cloud SDK/google-cloud-sdk/bin/sdk'
            if not (sdk / 'plink.exe').is_file():
                sdk = Path.home() / 'AppData/Local/Google/Cloud SDK/google-cloud-sdk/bin/sdk'
            self.plink = str(sdk / 'plink.exe')
            self.pscp = str(sdk / 'pscp.exe')
            if not fingerprint:
                raise ValueError('A pinned host fingerprint is required with PuTTY')
            return
        if fingerprint:
            host = target.split('@')[-1]
            scan = subprocess.run(['ssh-keyscan', '-T', '12', '-t', 'ed25519', host], capture_output=True, text=True, check=True)
            matches = []
            for line in scan.stdout.splitlines():
                parts = line.split()
                if len(parts) < 3:
                    continue
                digest = 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(parts[2])).digest()).decode().rstrip('=')
                if digest == fingerprint:
                    matches.append(line)
            if not matches:
                raise RuntimeError('SSH server host key does not match the pinned fingerprint')
            self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
            self.known_hosts.write_text('\n'.join(matches) + '\n', encoding='utf-8')

    @property
    def options(self):
        if self.plink:
            return ['-batch', '-i', self.key, '-hostkey', self.fingerprint]
        return ['-i', self.key, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'IdentitiesOnly=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={self.known_hosts}']

    def command(self, command, *, timeout=120):
        return subprocess.run([self.plink or 'ssh', *self.options, self.target, command], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout, check=True).stdout

    def python(self, program, *, timeout=120):
        encoded = base64.b64encode(program.encode()).decode()
        command = 'python3 -c ' + shlex.quote(f'import base64;exec(base64.b64decode({encoded!r}))')
        return self.command(command, timeout=timeout)

    def upload(self, local, remote):
        subprocess.run([self.pscp if self.plink else 'scp', *self.options, str(local), f'{self.target}:{remote}'], check=True)

    def download(self, remote, local):
        subprocess.run([self.pscp if self.plink else 'scp', *self.options, f'{self.target}:{remote}', str(local)], check=True)
