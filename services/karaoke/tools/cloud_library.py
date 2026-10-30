"""Foreground GPU library preparation; source files and metadata come from the VM."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from services.karaoke.assets import MODEL_SHA256, CONFIG_SHA256, canonical_json, sha256_file
from services.karaoke.tools.cloud_transport import CloudTransport

# Windows machines often default to cp1252; production song titles can be Unicode.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')

NAMES = ('instrumental.wav', 'vocals.wav', 'pitch_reference.json', 'karaoke_asset_manifest.json')
PARAMETERS = dict(segment_size=128, overlap=2, chunk_seconds=30, batch_size=1,
                  sample_rate=44100, device='cuda', precision='float32', chunking='sample-exact-v1')
CONFIG_VERSION = hashlib.sha256(canonical_json({'asset': CONFIG_SHA256, 'parameters': PARAMETERS})).hexdigest()


def connect(config):
    return CloudTransport(config['sshTarget'], config['sshKey'], config['knownHosts'], config.get('hostFingerprint'))


def rpc(cloud, payload):
    code = "import sys,json;sys.path.insert(0,'/opt/moodify-karaoke');from remote_store import handle;"
    code += 'print(json.dumps(handle(' + repr(payload) + ')))'
    return json.loads(cloud.python(code))


def validated_output(directory, song_id, source_hash):
    manifest = json.loads((directory / 'karaoke_asset_manifest.json').read_text(encoding='utf-8'))
    if (manifest['songId'] != song_id or manifest['status'] != 'prepared_local'
            or manifest['source']['sha256'] != source_hash
            or manifest['processing']['modelVersion'] != MODEL_SHA256
            or manifest['processing']['configVersion'] != CONFIG_VERSION):
        raise ValueError('Existing output does not match source/model/configuration')
    for item in manifest['assets'].values():
        if item['file'] not in NAMES:
            raise ValueError('Unexpected output filename')
        path = directory / item['file']
        if path.stat().st_size != item['bytes'] or sha256_file(path) != item['sha256']:
            raise ValueError('Local asset is incomplete or corrupt')
    return manifest


@contextmanager
def exclusive_run(path):
    with path.open('a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            handle.write(b'0')
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def save_report(path, results, started, complete=False):
    report = {'startedAt': started, 'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'complete': complete, 'counts': {}, 'songs': results}
    for row in results:
        status = row['status']
        report['counts'][status] = report['counts'].get(status, 0) + 1
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)
    return report


def run(args):
    config = json.loads(args.config.read_text(encoding='utf-8'))
    root = Path(config.get('localRoot', 'artifacts/karaoke/library')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cloud = connect(config)
    inventory = rpc(cloud, {'action': 'inventory'})
    (root / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.inventory_only:
        print(json.dumps({'tracks': len(inventory['songs']), 'available': sum(x['sourceExists'] for x in inventory['songs']),
                          'space': inventory['space']}))
        return
    image = config.get('prepareImage', 'dreayrt/audio_separator_for_karaoke:0.4.1-prep-gpu')
    if not args.skip_gpu_check:
        subprocess.run(['docker', 'run', '--rm', '--gpus', 'all', '--entrypoint', 'python', image, '-c',
                        "import torch; assert torch.cuda.is_available(), 'CUDA is not visible'; print(torch.cuda.get_device_name(0))"],
                       check=True, timeout=180)
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    report_path = root / (args.report or 'batch-report.json')
    rows, selected = [], []
    allowed_ids = set(args.song_id or [])
    for song in inventory['songs']:
        status = 'pending' if song['sourceExists'] else ('missing_mapping' if not song['localPath'] else 'missing_source')
        if allowed_ids and song['songId'] not in allowed_ids:
            status = 'not_selected'
        row = {**song, 'status': status}
        rows.append(row)
        if status == 'pending':
            selected.append(row)
    if args.limit:
        for row in selected[args.limit:]:
            row['status'] = 'not_selected'
        selected = selected[:args.limit]
    save_report(report_path, rows, started)
    with exclusive_run(root / 'batch.lock'):
        for index, row in enumerate(selected, 1):
            song_id = row['songId']
            print(f"[{index}/{len(selected)}] {song_id}: {row.get('name', '')}", flush=True)
            try:
                source = rpc(cloud, {'action': 'source', 'localPath': row['localPath']})
                if not source['exists']:
                    row['status'] = 'missing_source'
                    continue
                cache = root / 'sources'
                cache.mkdir(exist_ok=True)
                source_file = cache / (song_id + Path(source['path']).suffix)
                if not source_file.is_file() or sha256_file(source_file) != source['sha256']:
                    temp = source_file.with_suffix('.download')
                    cloud.download(source['path'], temp)
                    if sha256_file(temp) != source['sha256']:
                        raise ValueError('Downloaded source checksum mismatch')
                    temp.replace(source_file)
                row.update(status='source_downloaded', sourceSha256=source['sha256'])
                save_report(report_path, rows, started)
                version = hashlib.sha256(canonical_json({'source': source['sha256'], 'model': MODEL_SHA256,
                                                         'config': CONFIG_VERSION})).hexdigest()[:24]
                output_root = root / 'prepared'
                output_root.mkdir(exist_ok=True)
                output = output_root / f'{song_id}-{version}'
                if not output.exists():
                    log_path = root / (song_id + '.prepare.log')
                    with log_path.open('w', encoding='utf-8') as log:
                        subprocess.run(['docker', 'run', '--rm', '--gpus', 'all',
                                    '--mount', f'type=bind,source={cache},target=/input,readonly',
                                    '--mount', f'type=bind,source={output_root},target=/output', image,
                                    '--input', '/input/' + source_file.name, '--song-id', song_id,
                                    '--output-dir', '/output/' + output.name, '--device', 'cuda',
                                    '--cpu-threads', 'auto'], check=True, stdout=log, stderr=subprocess.STDOUT)
                manifest = validated_output(output, song_id, source['sha256'])
                row.update(status='prepared', assetVersion=version, output=str(output),
                           referenceStatus=manifest['scoringReference']['status'])
                save_report(report_path, rows, started)
                hashes = {name: sha256_file(output / name) for name in NAMES}
                payload = {'songId': song_id, 'assetVersion': version, 'localPath': row['localPath'],
                           'hashes': hashes, 'bytes': sum((output / name).stat().st_size for name in NAMES)}
                begin = rpc(cloud, {'action': 'begin', **payload})
                if begin.get('capacityBlocked'):
                    row.update(status='capacity_blocked', capacity=begin)
                    print('Disk budget reached. Batch stopped before upload.', flush=True)
                    break
                if not begin.get('alreadyPublished'):
                    for name in NAMES:
                        cloud.upload(output / name, begin['stage'] + '/' + name)
                result = rpc(cloud, {'action': 'publish', **payload})
                row.update(status=result['status'], uploadedBytes=payload['bytes'])
                print(json.dumps({'songId': song_id, 'status': row['status'], 'assetVersion': version,
                                  'bytes': payload['bytes']}), flush=True)
            except KeyboardInterrupt:
                row['status'] = 'interrupted'
                raise
            except Exception as exc:
                row.update(status='failed', error=str(exc)[:1200])
                print(f"Failed {song_id}: {type(exc).__name__}; see private report.", flush=True)
            finally:
                save_report(report_path, rows, started)
        result = save_report(report_path, rows, started, complete=not any(r['status'] in {'pending', 'capacity_blocked', 'interrupted'} for r in rows))
    print(json.dumps({'counts': result['counts'], 'report': str(report_path)}, ensure_ascii=False), flush=True)
    if any(r['status'] in {'failed', 'pending', 'capacity_blocked', 'interrupted'} for r in rows):
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('artifacts/karaoke/cloud-config.json'))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--song-id', action='append')
    parser.add_argument('--inventory-only', action='store_true')
    parser.add_argument('--skip-gpu-check', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--report', help='Report filename inside the local library directory')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    if args.report and Path(args.report).name != args.report:
        parser.error('--report must be a filename, not a path')
    run(args)


if __name__ == '__main__':
    main()
