import asyncio
import threading

import pytest

from services.karaoke.config import Settings
from services.karaoke import resources
from services.karaoke.runtime import Admission


@pytest.mark.parametrize("host", [4 * 1024**3, 16 * 1024**3, 24 * 10**9, 24 * 1024**3])
@pytest.mark.parametrize("percent", [30, 35])
def test_budget_stays_below_selected_environment_ceiling(host, percent):
    limit = resources.docker_budget(host, percent)
    assert 0 < limit <= host * percent / 100
    assert limit % 1024**2 == 0


def test_no_cap_is_valid_by_default_and_explicit_policy_is_checked(monkeypatch):
    monkeypatch.setattr(resources, "host_memory_bytes", lambda: 10000)
    monkeypatch.setattr(resources, "cgroup_memory_limit", lambda: None)
    assert resources.verify_memory_limit()["hard_limit_bytes"] is None
    with pytest.raises(RuntimeError, match="No hard memory"):
        resources.verify_memory_limit(30)
    monkeypatch.setattr(resources, "cgroup_memory_limit", lambda: 3001)
    with pytest.raises(RuntimeError, match="exceeds"):
        resources.verify_memory_limit(30)
    monkeypatch.setattr(resources, "cgroup_memory_limit", lambda: 2700)
    assert resources.verify_memory_limit(30)["effective_percent"] == 27


@pytest.mark.parametrize("environment", ["dev", "production"])
def test_environment_has_no_default_memory_cap(environment):
    assert Settings(api_key="test-key-long-enough-for-backend", environment=environment).memory_percent is None
    assert Settings(api_key="test-key-long-enough-for-backend", environment=environment, memory_percent=80).memory_percent == 80


def test_disconnected_request_keeps_model_and_files_leased_until_cpu_finishes(tmp_path):
    async def scenario():
        admission = Admission()
        lease = admission.acquire()
        folder = tmp_path / "request-test"
        folder.mkdir()
        lease.workspace = folder
        entered, release = threading.Event(), threading.Event()

        def cpu_work():
            entered.set()
            assert release.wait(3)
            assert folder.exists()

        task = asyncio.create_task(lease.compute(cpu_work))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        lease.request_finished()
        assert folder.exists()
        assert admission.acquire() is None
        release.set()
        for _ in range(100):
            if not admission.tasks:
                break
            await asyncio.sleep(.01)
        assert not folder.exists()
        next_lease = admission.acquire()
        assert next_lease is not None
        next_lease.request_finished()

    asyncio.run(scenario())
