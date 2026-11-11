"""Model nesneleri: istek hızı sınırı, canlı akış ve kullanım takibi.

Her model çağrısı `llm_olustur` ile oluşturulan nesnenin `call` yöntemi üzerinden geçer;
CrewAI ajanları da aynı nesneyi kullandığı için sınır ve akış onlara da uygulanır.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable

from .hatalar import Durduruldu
from .office import make_llm
from .settings import genel_ayarlar, saglayici


class HizSiniri:
    """Sağlayıcı başına kayan pencere: son 60 saniyede en fazla `rpm` istek."""

    def __init__(self) -> None:
        self._kilit = threading.Lock()
        self._zamanlar: dict[str, deque] = defaultdict(deque)

    def bekle(self, anahtar: str, rpm: int, iptal: threading.Event | None = None,
              bildir: Callable[[float], None] | None = None) -> float:
        if rpm <= 0:
            return 0.0
        toplam, bildirildi = 0.0, False
        while True:
            with self._kilit:
                q, simdi = self._zamanlar[anahtar], time.monotonic()
                while q and simdi - q[0] >= 60:
                    q.popleft()
                if len(q) < rpm:
                    q.append(simdi)
                    return toplam
                sure = 60 - (simdi - q[0]) + 0.05
            if bildir and not bildirildi:
                bildir(sure)
                bildirildi = True
            if iptal is not None:
                if iptal.wait(sure):
                    raise Durduruldu()
            else:
                time.sleep(sure)
            toplam += sure


HIZ = HizSiniri()


def llm_olustur(model: str, *, stream: bool = False, iptal: threading.Event | None = None,
                bekleme_bildir: Callable[[float], None] | None = None):
    """Hız sınırına uyan bir model nesnesi döndürür."""
    llm = make_llm(model, stream=stream)
    anahtar = saglayici(model) or "diger"
    orijinal = llm.call

    def call(*args, **kwargs):
        rpm = int(genel_ayarlar()["hiz"].get(anahtar, 0) or 0)
        HIZ.bekle(anahtar, rpm, iptal, bekleme_bildir)
        return orijinal(*args, **kwargs)

    # pydantic modeli: örnek özniteliği olarak yöntemi gölgele (CrewAI de llm.call'ı çağırır)
    object.__setattr__(llm, "call", call)
    return llm


def kullanim(llm) -> tuple[int, int]:
    """Bir model nesnesinin şimdiye kadarki (giriş, çıkış) token sayısı."""
    try:
        u = llm.get_token_usage_summary()
        return int(u.prompt_tokens or 0), int(u.completion_tokens or 0)
    except Exception:
        return 0, 0


# ------------------------------------------------------------------ canlı akış
_akis_dinleyicileri: dict[str, Callable[[int, str], None]] = {}
_akis_kilit = threading.Lock()
_akis_kayitli = False


def _akis_dinleyicisini_kur() -> None:
    global _akis_kayitli
    with _akis_kilit:
        if _akis_kayitli:
            return
        from crewai.events import crewai_event_bus
        from crewai.events.types.llm_events import LLMStreamChunkEvent

        @crewai_event_bus.on(LLMStreamChunkEvent)
        def _parca(_kaynak, olay):  # CrewAI işleyicileri ayrı iş parçacıklarında çalıştırır
            fn = _akis_dinleyicileri.get(olay.agent_id or "")
            if fn and olay.chunk and not olay.tool_call:
                fn(olay.emission_sequence or 0, olay.chunk)

        _akis_kayitli = True


class CanliTampon:
    """Bir ajanın akış parçalarını sırasıyla biriktirir, aralıklarla tek parça olarak iletir."""

    def __init__(self, gonder: Callable[[str], None], aralik: float = 0.6):
        self._gonder = gonder
        self._parcalar: list[tuple[int, str]] = []
        self._kilit = threading.Lock()
        self._dur = threading.Event()
        self._is = threading.Thread(target=self._dongu, daemon=True)

    def ekle(self, sira: int, parca: str) -> None:
        with self._kilit:
            self._parcalar.append((sira, parca))

    def _bosalt(self) -> None:
        with self._kilit:
            parcalar, self._parcalar = sorted(self._parcalar), []
        if parcalar:
            self._gonder("".join(p for _, p in parcalar))

    def _dongu(self) -> None:
        while not self._dur.wait(0.6):
            self._bosalt()

    def __enter__(self):
        self._is.start()
        return self

    def __exit__(self, *_):
        self._dur.set()
        self._is.join(timeout=2)
        self._bosalt()


def akis_baglan(agent_id: str, tampon: CanliTampon) -> None:
    _akis_dinleyicisini_kur()
    _akis_dinleyicileri[agent_id] = tampon.ekle


def akis_ayir(agent_id: str) -> None:
    _akis_dinleyicileri.pop(agent_id, None)
