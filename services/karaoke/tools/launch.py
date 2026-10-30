"""Launch a CPU score API with no default memory cap, bound to loopback."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess

from services.karaoke.config import PRODUCTION_URL
from services.karaoke.resources import docker_budget

IMAGE = os.environ.get("KARAOKE_SCORING_IMAGE", "dreayrt/audio_separator_for_karaoke:0.4.3-score")


def docker_info():
    return json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .}}'], text=True))


def prepare_env(path, environment, threads, percent=None):
    values = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key] = value
    if not values.get('AI_API_KEY'):
        values['AI_API_KEY'] = secrets.token_urlsafe(32)
    values.update(AI_ENV=environment, AI_CPU_THREADS=str(threads), AI_DEVICE='cpu')
    values.pop('AI_MEMORY_PERCENT', None)
    if percent is not None:
        values['AI_MEMORY_PERCENT'] = str(percent)
    path.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    if os.name != 'nt':
        path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', choices=('dev', 'production'), default='dev')
    parser.add_argument('--image', default=IMAGE)
    parser.add_argument('--name')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--url', help='Public API base URL reported to the backend')
    limits = parser.add_mutually_exclusive_group()
    limits.add_argument('--memory-percent', type=int, help='Optional explicit host RAM percentage (1-100)')
    limits.add_argument('--memory-mib', type=int, help='Optional explicit Docker memory limit in MiB')
    parser.add_argument('--cpu-threads', type=int, default=1)
    parser.add_argument('--cpus', type=float, default=1.0)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.memory_percent is not None and not 1 <= args.memory_percent <= 100:
        parser.error('memory-percent must be between 1 and 100')
    if args.memory_mib is not None and args.memory_mib < 128:
        parser.error('memory-mib must be at least 128')
    if not 1 <= args.port <= 65535 or not 1 <= args.cpu_threads <= 64:
        parser.error('Invalid port or CPU threads')
    info = docker_info()
    if not 0 < args.cpus <= info['NCPU'] or args.cpu_threads > max(1, int(args.cpus)):
        parser.error('CPU threads/budget must fit the CPUs allocated to this container')
    limit = None
    if args.memory_percent is not None:
        limit = docker_budget(info['MemTotal'], args.memory_percent)
    elif args.memory_mib is not None:
        limit = args.memory_mib * 1024**2
    if limit is not None and limit > info['MemTotal']:
        parser.error('Explicit memory allocation exceeds host RAM')
    env_file = (args.env_file or Path(f'.env.karaoke.{args.env}.local')).resolve()
    command = ['docker', 'run', '-d', '--restart', 'unless-stopped', '--name', args.name or f'karaoke-score-{args.env}',
               '--label', 'karaoke.score-service=true', '--cpus', str(args.cpus), '--env-file', str(env_file),
               '-p', f'{args.bind}:{args.port}:8000']
    if limit is not None:
        command += ['--memory', str(limit), '--memory-swap', str(limit)]
    command.append(args.image)
    public_url = args.url or (PRODUCTION_URL if args.env == 'production' else f'http://127.0.0.1:{args.port}')
    print(json.dumps({'environment': args.env, 'image': args.image, 'device': 'cpu', 'api_url': public_url,
                      'limit_bytes': limit, 'memory_ceiling_percent': args.memory_percent,
                      'docker_host_memory_bytes': info['MemTotal'], 'cpu_threads': args.cpu_threads,
                      'command': command}, indent=2))
    if not args.dry_run:
        prepare_env(env_file, args.env, args.cpu_threads, args.memory_percent)
        subprocess.run(command, check=True)
        print('Backend credentials are in the private env file; they are not printed.')


if __name__ == '__main__':
    main()
