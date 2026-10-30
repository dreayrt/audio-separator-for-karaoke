import json
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import pytest
from services.karaoke.api import create_app
from services.karaoke.config import Settings
from services.karaoke.errors import ServiceError
from services.karaoke import resources

KEY = 'unit-test-backend-key-never-publish'
AUTH = {'Authorization': 'Bearer ' + KEY}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, 'cgroup_memory_limit', lambda: None)
    settings = Settings(api_key=KEY, environment='test', temp_dir=tmp_path,
                        max_request_bytes=8192, max_reference_bytes=4096)
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, app


def upload(client, **kwargs):
    return client.post('/v1/score', headers=AUTH,
                       files={'recording': ('../../voice.wav', b'audio'), 'reference': ('ref.json', b'{}')}, **kwargs)


def clean(app):
    assert not list(app.state.karaoke.workspaces.directory.glob('request-*'))


def test_startup_without_cgroup_cap_and_score_only_routes(service):
    client, app = service
    assert client.get('/health/ready').status_code == 200
    assert client.get('/v1/info').status_code == 401
    info = client.get('/v1/info', headers=AUTH).json()
    assert info['service_mode'] == 'score-only'
    assert info['memory_policy']['hard_limit_bytes'] is None
    assert client.post('/v1/separate', headers=AUTH).status_code == 404
    assert client.post('/v1/references', headers=AUTH).status_code == 404
    clean(app)


def test_auth_and_body_limit_before_processing(service):
    client, app = service
    assert client.post('/v1/score', content=b'x'*10000).status_code == 401
    assert client.post('/v1/score', headers=AUTH, content=b'x'*10000).status_code == 413
    clean(app)


def test_score_upload_cleanup_and_request_id(service, monkeypatch):
    client, app = service
    def score(rec, ref, work, settings, timing, request_id):
        assert rec.read_bytes() == b'audio' and ref.read_bytes() == b'{}'
        return {'request_id': request_id, 'score': {'overall': 75}}
    monkeypatch.setattr('services.karaoke.api.score_recording', score)
    response = upload(client, data={'request_id': 'backend-request-1'})
    assert response.status_code == 200
    assert response.headers['x-request-id'] == 'backend-request-1'
    assert response.json()['score']['overall'] == 75
    clean(app)


def test_incremental_feature_score_api(service, monkeypatch):
    client, app = service
    monkeypatch.setattr("services.karaoke.api.read_reference", lambda *args: object())
    def score(reference, features, timing, request_id):
        assert features["duration_seconds"] == 1
        assert len(features["f0_hz"]) == 44
        return {"request_id": request_id, "score": {"overall": 66}}
    monkeypatch.setattr("services.karaoke.api.score_features", score)
    features = {
        "duration_seconds": 1,
        "f0_hz": [None] * 44,
        "voiced_probability": [0] * 44,
        "rms_dbfs": -20,
        "clipped_fraction": 0,
    }
    response = client.post(
        "/v1/score/features",
        headers=AUTH,
        data={"timing": "{}"},
        files={
            "features": ("features.json", json.dumps(features), "application/json"),
            "reference": ("reference.json", b"{}", "application/json"),
        },
    )
    assert response.status_code == 200
    assert response.json()["score"]["overall"] == 66
    clean(app)


def test_concurrency_rejected_until_actual_computation_finishes(service, monkeypatch):
    client, app = service
    entered, release = threading.Event(), threading.Event()
    def score(*args):
        entered.set()
        assert release.wait(5)
        return {'score': {'overall': 100}}
    monkeypatch.setattr('services.karaoke.api.score_recording', score)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(upload, client)
        assert entered.wait(3)
        busy = upload(client)
        assert busy.status_code == 503
        assert busy.headers['Retry-After'] == '5'
        assert client.get('/health/live').status_code == 200
        release.set()
        assert first.result().status_code == 200
    clean(app)


def test_invalid_timing_and_missing_reference_are_rejected(service):
    client, app = service
    assert upload(client, data={'timing': '{"capture_latency_ms":-1}'}).status_code == 400
    assert client.post('/v1/score', headers=AUTH, files={'recording': ('a.wav', b'a')}).status_code == 400
    clean(app)


def test_worker_error_releases_workspace_and_lease(service, monkeypatch):
    client, app = service
    def fail(*args):
        raise ServiceError('INVALID_AUDIO', 'invalid recording')
    monkeypatch.setattr('services.karaoke.api.score_recording', fail)
    assert upload(client).status_code == 400
    clean(app)
    lease = app.state.karaoke.admission.acquire()
    assert lease is not None
    lease.request_finished()
