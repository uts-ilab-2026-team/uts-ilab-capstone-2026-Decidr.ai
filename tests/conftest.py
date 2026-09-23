"""Automated tests never contact a running model."""

import pytest


@pytest.fixture(autouse=True)
def offline_ollama(monkeypatch):
    from decidr.interpretation import OllamaInterpreter
    from decidr.interpretation_v1 import OllamaInterpreter as LegacyInterpreter

    def unavailable(self, payload):
        raise ConnectionError("Mocked offline Ollama")
    for adapter in (OllamaInterpreter, LegacyInterpreter):
        monkeypatch.setattr(adapter, "available", lambda self: False)
        monkeypatch.setattr(adapter, "_http", unavailable)
