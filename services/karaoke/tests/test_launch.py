import json
import sys
import pytest
from services.karaoke.tools import launch


def test_no_implicit_memory_limit_and_loopback_port(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['launch', '--env', 'production', '--dry-run'])
    monkeypatch.setattr(launch, 'docker_info', lambda: dict(MemTotal=8*1024**3, NCPU=2))
    launch.main()
    result = json.loads(capsys.readouterr().out)
    assert result['limit_bytes'] is None
    assert '--memory' not in result['command']
    assert '--memory-swap' not in result['command']
    assert '127.0.0.1:8003:8000' in result['command']
    assert result['device'] == 'cpu'
    assert result['image'].endswith(':0.4.3-score')


def test_explicit_memory_allocation_is_optional_and_not_capped_at_35(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['launch', '--memory-percent', '80', '--dry-run'])
    monkeypatch.setattr(launch, 'docker_info', lambda: dict(MemTotal=8*1024**3, NCPU=2))
    launch.main()
    result = json.loads(capsys.readouterr().out)
    assert result['limit_bytes'] > 8*1024**3*.35
    assert '--memory' in result['command']


def test_env_migration_preserves_key_and_removes_obsolete_cap(tmp_path):
    path = tmp_path / 'private.env'
    path.write_text('AI_API_KEY=existing-private-backend-key\nAI_MEMORY_PERCENT=35\n')
    launch.prepare_env(path, 'production', 1)
    assert 'AI_API_KEY=existing-private-backend-key' in path.read_text()
    assert 'AI_MEMORY_PERCENT' not in path.read_text()
    assert 'AI_DEVICE=cpu' in path.read_text()


def test_invalid_percent_is_rejected_before_docker(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['launch', '--memory-percent', '101', '--dry-run'])
    monkeypatch.setattr(launch, 'docker_info', lambda: pytest.fail('invalid policy reached Docker'))
    with pytest.raises(SystemExit):
        launch.main()
