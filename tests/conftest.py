"""Testler gerçek ayarlara, çıktılara ve API anahtarlarına dokunmaz.

Ortam değişkenleri plaza modülleri içe aktarılmadan ÖNCE geçici bir klasöre yönlendirilir.
"""

import os
import tempfile
from pathlib import Path

_GECICI = Path(tempfile.mkdtemp(prefix="plaza-test-"))
os.environ["PLAZA_OFIS_AYAR"] = str(_GECICI / "ofis.json")
os.environ["PLAZA_CIKTI"] = str(_GECICI / "cikti")
os.environ["PLAZA_ZAMANLANMIS"] = str(_GECICI / "zamanlanmis.json")
# CrewAI içe aktarılırken .env dosyasını okur; anahtarlar ondan SONRA temizlenmeli ki
# testler hiçbir zaman gerçek bir yapay zekâ servisine istek göndermesin.
import crewai  # noqa: E402,F401

for anahtar in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(anahtar, None)
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:9"  # yerel modeller de "çalışmıyor" görünsün

import pytest  # noqa: E402


@pytest.fixture
def ayar_dosyasi(tmp_path):
    return tmp_path / "ofis.json"


@pytest.fixture
def hizli(monkeypatch):
    """Simülasyondaki beklemeleri kaldırır."""
    import plaza.orchestrator as orc

    monkeypatch.setattr(orc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(orc, "BEKLEMELER", (0.01, 0.01, 0.01))
    return orc
