from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.karaoke.config import Settings
from services.karaoke.engine import configure_device

KEY = "device-tests-private-backend-key"


def fake_torch(available):
    return SimpleNamespace(device=lambda name: SimpleNamespace(type=name.split(":")[0]),
                           cuda=SimpleNamespace(is_available=Mock(return_value=available),
                                                set_per_process_memory_fraction=Mock()))


def test_score_api_defaults_to_cpu_without_memory_cap():
    dev, production = Settings(api_key=KEY, environment="dev"), Settings(api_key=KEY)
    assert (dev.device, dev.memory_percent) == ("cpu", None)
    assert (production.device, production.memory_percent) == ("cpu", None)


def test_cuda_uses_selected_device_and_vram_fraction():
    torch = fake_torch(True)
    settings = SimpleNamespace(environment="local", device="cuda", gpu_memory_fraction=.75)
    assert configure_device(settings, torch).type == "cuda"
    torch.cuda.set_per_process_memory_fraction.assert_called_once_with(.75, 0)


def test_missing_cuda_reports_failure_instead_of_claiming_gpu_acceleration():
    with pytest.raises(RuntimeError, match="CUDA is unavailable"):
        configure_device(SimpleNamespace(environment="local", device="cuda"), fake_torch(False))


def test_production_stays_on_cpu_even_on_gpu_machine():
    torch = fake_torch(True)
    assert configure_device(Settings(api_key=KEY), torch).type == "cpu"
    torch.cuda.is_available.assert_not_called()
    torch.cuda.set_per_process_memory_fraction.assert_not_called()
    with pytest.raises(ValueError, match="score-only API uses CPU"):
        Settings(api_key=KEY, device="cuda")


def test_environment_defaults_and_overrides(monkeypatch):
    for name in ("AI_MEMORY_PERCENT", "AI_DEVICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_API_KEY", KEY)
    monkeypatch.setenv("AI_ENV", "production")
    assert Settings.from_env().memory_percent is None
    monkeypatch.setenv("AI_ENV", "dev")
    assert Settings.from_env().device == "cpu"
    monkeypatch.setenv("AI_DEVICE", "cpu")
    assert Settings.from_env().device == "cpu"
    monkeypatch.setenv("AI_MEMORY_PERCENT", "35")
    assert Settings.from_env().memory_percent == 35
