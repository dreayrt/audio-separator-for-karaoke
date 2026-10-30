"""SSH-only helper installed on the VM. Mongo credentials stay on the VM."""

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit

ROOT = Path('/srv/moodify/karaoke')
NAMES = ('instrumental.wav', 'vocals.wav', 'pitch_reference.json', 'karaoke_asset_manifest.json')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def container_env(name):
    obj = json.loads(subprocess.check_output(['sudo', '-n', 'docker', 'inspect', name], text=True))[0]
    return dict(x.split('=', 1) for x in obj['Config']['Env'] if '=' in x)


def mongo(js):
    env = container_env('moodify-mongo')
    database = container_env('moodify-backend').get('MONGODB_DATABASE', 'music_streaming')
    args = ['sudo', '-n', 'docker', 'exec', 'moodify-mongo', 'mongosh', '--quiet']
    if env.get('MONGO_INITDB_ROOT_USERNAME'):
        args += ['-u', env['MONGO_INITDB_ROOT_USERNAME'], '-p', env['MONGO_INITDB_ROOT_PASSWORD'], '--authenticationDatabase', 'admin']
    program = 'const d=db.getSiblingDB(' + json.dumps(database) + ');' + js
    result = subprocess.run(args + ['--eval', program], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('MongoDB operation failed (credentials and query details suppressed)')
    return json.loads(result.stdout.strip())


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,255}', value):
        raise ValueError('Invalid song ID')
    return value


def source_path(local_path):
    path = urlsplit(local_path).path if local_path.startswith(('http://', 'https://')) else local_path
    path = path.replace(chr(92), '/').lstrip('/')
    if '..' in path.split('/'):
        raise ValueError('Source path traversal')
    if path.startswith('data/audio/'):
        return Path('/opt/music-data-collector') / path
    if path.startswith('uploads/'):
        return Path('/opt/moodify') / path
    return None


def inventory():
    data = mongo('print(EJSON.stringify(d.tracks.find({}, {_id:1,name:1,local_path:1,duration_ms:1}).toArray()));')
    songs = []
    for row in data:
        raw_id = row['_id']
        song_id = raw_id.get('$oid') if isinstance(raw_id, dict) else str(raw_id)
        path = row.get('local_path') or ''
        file = source_path(path) if path else None
        songs.append({'songId': song_id, 'originalTrackId': raw_id, 'name': row.get('name'),
                      'localPath': path, 'remoteSource': str(file) if file else None,
                      'sourceExists': bool(file and file.is_file()), 'bytes': file.stat().st_size if file and file.is_file() else None,
                      'durationMs': row.get('duration_ms')})
    return {'songs': songs, 'sourceBase': container_env('moodify-backend').get('GCP_AUDIO_BASE_URL', 'https://moodify.click/'),
            'space': space(), 'root': str(ROOT)}


def space():
    total, used, free = shutil.disk_usage(ROOT if ROOT.exists() else '/')
    return {'total': total, 'used': used, 'free': free, 'maxUsedFraction': 0.8}


def stage_path(song_id, version):
    safe_id(song_id)
    if not re.fullmatch('[a-f0-9]{24}', version):
        raise ValueError('Invalid asset version')
    return ROOT / '.incoming' / (song_id + '-' + version)


def handle(payload):
    action = payload['action']
    if action == 'inventory':
        return inventory()
    if action == 'space':
        return space()
    if action == 'source':
        path = source_path(payload['localPath'])
        if not path or not path.is_file():
            return {'exists': False}
        return {'exists': True, 'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}
    song_id, version = safe_id(payload['songId']), payload['assetVersion']
    stage = stage_path(song_id, version)
    final = ROOT / song_id / version
    if action == 'begin':
        hashes = payload['hashes']
        if set(hashes) != set(NAMES):
            raise ValueError('Incomplete asset list')
        if final.exists() and all((final / n).is_file() and digest(final / n) == hashes[n] for n in NAMES):
            return {'alreadyPublished': True, 'path': str(final)}
        if final.exists():
            raise ValueError('Version directory already exists with different contents')
        usage = space()
        existing = sum(p.stat().st_size for p in stage.glob('*') if p.is_file()) if stage.exists() else 0
        if usage['used'] + max(0, payload['bytes'] - existing) > usage['total'] * 0.8:
            return {'capacityBlocked': True, 'space': usage, 'requiredBytes': payload['bytes']}
        stage.mkdir(parents=True, exist_ok=True)
        return {'stage': str(stage), 'alreadyPublished': False}
    if action == 'publish':
        directory = final if final.exists() else stage
        if not directory.is_dir() or any(not (directory / n).is_file() or digest(directory / n) != payload['hashes'][n] for n in NAMES):
            raise ValueError('Uploaded files failed SHA-256 verification')
        manifest = json.loads((directory / 'karaoke_asset_manifest.json').read_text())
        if manifest['songId'] != song_id or manifest['status'] != 'prepared_local':
            raise ValueError('Unexpected manifest identity or status')
        for role in ('instrumental', 'vocals', 'pitchReference'):
            item = manifest['assets'][role]
            if item['file'] not in NAMES or digest(directory / item['file']) != item['sha256']:
                raise ValueError('Manifest asset checksum mismatch')
        current_source = source_path(payload['localPath'])
        if not current_source or not current_source.is_file() or digest(current_source) != manifest['source']['sha256']:
            raise ValueError('Original source changed before publishing')
        if directory == stage:
            final.parent.mkdir(parents=True, exist_ok=True)
            stage.rename(final)
        key = f'karaoke/{song_id}/{version}/'
        assets = {}
        for role, item in manifest['assets'].items():
            assets[role] = {k: v for k, v in item.items() if k != 'file'}
            assets[role]['storageKey'] = key + item['file']
        document = {'songId': song_id, 'status': 'ready', 'assetVersion': version,
                    'source': {**manifest['source'], 'localPath': payload['localPath']},
                    'assets': assets, 'processing': manifest['processing'], 'scoringReference': manifest['scoringReference'],
                    'storage': {'provider': 'gcp-vm', 'root': str(ROOT), 'baseUrl': 'https://moodify.click/'}}
        encoded = base64.b64encode(json.dumps(document).encode()).decode()
        script = 'const doc=JSON.parse(Buffer.from(' + json.dumps(encoded) + ',"base64").toString());'
        script += 'const ids=[doc.songId]; if(ObjectId.isValid(doc.songId)) ids.push(new ObjectId(doc.songId));'
        script += 'const t=d.tracks.findOne({_id:{$in:ids}}); if(!t || t.local_path!==doc.source.localPath) throw new Error("Track mapping changed");'
        script += 'doc.originalTrackId=t._id; doc.updatedAt=new Date();'
        script += 'd.karaoke_assets.createIndex({songId:1},{unique:true});'
        script += 'd.karaoke_assets.updateOne({songId:doc.songId},{$set:doc,$setOnInsert:{createdAt:new Date()}},{upsert:true});'
        script += 'print(JSON.stringify({status:"ready",songId:doc.songId,assetVersion:doc.assetVersion}));'
        return mongo(script)
    raise ValueError('Unknown action')
