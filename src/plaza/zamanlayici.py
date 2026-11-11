"""Zamanlanmış görevler: belirli saatlerde (isteğe bağlı olarak belirli günlerde) CEO'ya görev verir.

Görevler `zamanlanmis.json` dosyasında tutulur. Plaza Ofis açık olduğu sürece her 20 saniyede
bir kontrol edilir; bilgisayar kapalıyken kaçan görevler sonradan çalıştırılmaz.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

DOSYA = Path(os.getenv("PLAZA_ZAMANLANMIS", "zamanlanmis.json"))
GUNLER = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]  # datetime.weekday() sırası
_kilit = threading.Lock()


def _oku(dosya: Path = DOSYA) -> list[dict]:
    try:
        return json.loads(dosya.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _yaz(liste: list[dict], dosya: Path = DOSYA) -> None:
    dosya.write_text(json.dumps(liste, ensure_ascii=False, indent=2), encoding="utf-8")


def listele(dosya: Path = DOSYA) -> list[dict]:
    return _oku(dosya)


def _dogrula(veri: dict) -> dict:
    talep = str(veri.get("talep", "")).strip()
    saat = str(veri.get("saat", "")).strip()
    if not talep:
        raise ValueError("Görev metni boş olamaz.")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", saat):
        raise ValueError("Saat SS:DD biçiminde olmalı (ör. 09:30).")
    gunler = sorted({int(g) for g in veri.get("gunler", []) if 0 <= int(g) <= 6})
    return {
        "talep": talep, "saat": saat, "gunler": gunler,
        "simulasyon": bool(veri.get("simulasyon", False)),
        "aktif": bool(veri.get("aktif", True)),
    }


def ekle(veri: dict, dosya: Path = DOSYA) -> dict:
    kayit = {"id": uuid.uuid4().hex[:8], **_dogrula(veri), "son_calisma": None, "son_sonuc": None}
    with _kilit:
        liste = _oku(dosya)
        liste.append(kayit)
        _yaz(liste, dosya)
    return kayit


def guncelle(zid: str, veri: dict, dosya: Path = DOSYA) -> dict:
    with _kilit:
        liste = _oku(dosya)
        for k in liste:
            if k["id"] == zid:
                k.update(_dogrula({**k, **veri}))
                _yaz(liste, dosya)
                return k
    raise KeyError(zid)


def sil(zid: str, dosya: Path = DOSYA) -> None:
    with _kilit:
        liste = _oku(dosya)
        yeni = [k for k in liste if k["id"] != zid]
        if len(yeni) == len(liste):
            raise KeyError(zid)
        _yaz(yeni, dosya)


def zamani_geldi(kayit: dict, simdi: datetime) -> bool:
    """Bugün, belirtilen saat geçmiş ve bu dakika için henüz çalışmamışsa True."""
    if not kayit.get("aktif"):
        return False
    if kayit.get("gunler") and simdi.weekday() not in kayit["gunler"]:
        return False
    if simdi.strftime("%H:%M") < kayit["saat"]:
        return False
    son = kayit.get("son_calisma") or ""
    bu_slot = simdi.strftime("%Y-%m-%d") + " " + kayit["saat"]
    # Saat geçtikten sonraki 10 dakika içinde bir kez çalış (uygulama o an kapalıysa kaçır)
    gecen = (simdi - simdi.replace(hour=int(kayit["saat"][:2]), minute=int(kayit["saat"][3:]),
                                   second=0, microsecond=0)).total_seconds()
    return son < bu_slot and gecen < 600


def kontrol_et(calistir: Callable[[dict], str], dosya: Path = DOSYA, simdi: datetime | None = None) -> list[str]:
    """Zamanı gelen görevleri çalıştırır; çalıştırılanların kimliklerini döndürür."""
    simdi = simdi or datetime.now()
    calisan = []
    with _kilit:
        liste = _oku(dosya)
        hazir = [k for k in liste if zamani_geldi(k, simdi)]
        for k in hazir:
            k["son_calisma"] = simdi.strftime("%Y-%m-%d") + " " + k["saat"]
        if hazir:
            _yaz(liste, dosya)
    for k in hazir:
        try:
            sonuc = calistir(k)
        except Exception as e:  # noqa: BLE001 — sonucu kayda yaz
            sonuc = f"başlatılamadı: {getattr(e, 'detail', None) or e}"
        with _kilit:
            liste = _oku(dosya)
            for x in liste:
                if x["id"] == k["id"]:
                    x["son_sonuc"] = f"{simdi:%d.%m %H:%M} — {sonuc}"
            _yaz(liste, dosya)
        calisan.append(k["id"])
    return calisan


def baslat(calistir: Callable[[dict], str], aralik: float = 20.0) -> threading.Event:
    dur = threading.Event()

    def dongu() -> None:
        while not dur.wait(aralik):
            try:
                kontrol_et(calistir)
            except Exception:  # noqa: BLE001 — zamanlayıcı hiçbir hatada durmasın
                pass

    threading.Thread(target=dongu, daemon=True, name="plaza-zamanlayici").start()
    return dur
