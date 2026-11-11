"""Plaza'nın temel yapı taşları: organizasyon şeması ve model nesnesi.

İş akışı `orchestrator.IsAkisi`, ayarlar `settings.load_office` içindedir.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml
from crewai import LLM

DEFAULT_MODEL = "anthropic/claude-opus-5-5"


def load_org(path: Path | None = None) -> dict:
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("plaza.config").joinpath("departments.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def make_llm(model: str, stream: bool = False) -> LLM:
    # max_tokens açıkça veriliyor: çok büyük değerler akışsız (non-streaming) isteklerde
    # SDK zaman aşımı kontrolüne takılır. temperature verilmiyor (yeni modeller reddediyor).
    return LLM(model=model, max_tokens=16000, stream=stream)
