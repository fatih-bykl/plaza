"""Plaza Ofis: kuşbakışı ofis arayüzünü sunan yerel web sunucusu.

    uv run plaza-ofis            # http://127.0.0.1:8770 adresini açar
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .orchestrator import Durduruldu, IsAkisi
from .settings import (
    MAX_MASA,
    MODELLER,
    departman_adlandir,
    departman_ekle,
    departman_kaldir,
    load_office,
    masa_ayari_kaydet,
    masa_ayarini_sil,
    masa_ekle,
    masa_kaldir,
    ofisi_sifirla,
)
from .tools import TOOL_TYPES

WEB = Path(__file__).parent / "web"
CIKTI = Path(os.getenv("PLAZA_CIKTI", "cikti")).resolve()


@dataclass
class Is:
    id: str
    talep: str
    klasor: Path
    olaylar: list[dict] = field(default_factory=list)
    calisiyor: bool = True
    iptal: threading.Event = field(default_factory=threading.Event)


class Yayin:
    """İş parçacığından gelen olayları SSE abonelerine iletir."""

    def __init__(self) -> None:
        self.kilit = threading.Lock()
        self.aboneler: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self.is_: Is | None = None

    def yayinla(self, is_: Is, tip: str, **veri) -> None:
        olay = {"tip": tip, "zaman": time.time(), "is_id": is_.id, **veri}
        with self.kilit:
            is_.olaylar.append(olay)
            for loop, q in self.aboneler:
                loop.call_soon_threadsafe(q.put_nowait, olay)


yayin = Yayin()
app = FastAPI(title="Plaza Ofis")


def _api_anahtari_var() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/ofis")
def ofis() -> dict:
    return {
        **load_office().to_dict(),
        "modeller": MODELLER,
        "araclar": list(TOOL_TYPES),
        "api_anahtari": _api_anahtari_var(),
        "max_masa": MAX_MASA,
    }


class MasaAyari(BaseModel):
    isim: str | None = None
    model: str | None = None
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    tools: list[str] | None = None
    aktif: bool | None = None


@app.put("/api/masa/{key}")
def masa_kaydet(key: str, ayar: MasaAyari) -> dict:
    office = load_office()
    try:
        office.desk(key)
    except KeyError:
        raise HTTPException(404, "Böyle bir masa yok.")
    degerler = ayar.model_dump(exclude_none=True)
    if key == "ceo":
        degerler.pop("tools", None)
        degerler.pop("aktif", None)
    try:
        masa_ayari_kaydet(key, degerler)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return ofis()


@app.delete("/api/masa/{key}")
def masa_sifirla(key: str) -> dict:
    masa_ayarini_sil(key)
    return ofis()


def _degistir(islem, *args) -> dict:
    try:
        islem(*args)
    except KeyError:
        raise HTTPException(404, "Bulunamadı.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return ofis()


class DepartmanIstegi(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class YeniMasa(BaseModel):
    isim: str = ""
    role: str = Field(min_length=1, max_length=60)
    goal: str = ""
    backstory: str = ""
    model: str = ""
    tools: list[str] = ["file_read", "file_write"]


@app.post("/api/departman")
def departman_olustur(istek: DepartmanIstegi) -> dict:
    return _degistir(departman_ekle, istek.name)


@app.put("/api/departman/{dkey}")
def departman_guncelle(dkey: str, istek: DepartmanIstegi) -> dict:
    return _degistir(departman_adlandir, dkey, istek.name)


@app.delete("/api/departman/{dkey}")
def departman_sil(dkey: str) -> dict:
    return _degistir(departman_kaldir, dkey)


@app.post("/api/departman/{dkey}/masa")
def masa_olustur(dkey: str, istek: YeniMasa) -> dict:
    return _degistir(masa_ekle, dkey, istek.model_dump())


@app.delete("/api/calisan/{key}")
def calisan_sil(key: str) -> dict:
    return _degistir(masa_kaldir, key)


@app.post("/api/ofis/sifirla")
def ofis_sifirla() -> dict:
    return _degistir(ofisi_sifirla)


class GorevIstegi(BaseModel):
    talep: str = Field(min_length=1)
    simulasyon: bool = False
    max_revizyon: int = Field(default=1, ge=0, le=3)


def _isi_yurut(is_: Is, office, simulasyon: bool, max_revizyon: int) -> None:
    def emit(tip: str, **veri) -> None:
        yayin.yayinla(is_, tip, **veri)

    akis = IsAkisi(office, is_.talep, emit, is_.klasor, simulasyon, max_revizyon, is_.iptal)
    try:
        sonuc = akis.calistir()
        is_.klasor.mkdir(parents=True, exist_ok=True)
        (is_.klasor / "SONUC.md").write_text(sonuc, encoding="utf-8")
        dosyalar = sorted(str(p.relative_to(is_.klasor)) for p in is_.klasor.rglob("*") if p.is_file())
        emit("is_bitti", sonuc=sonuc, klasor=is_.klasor.name, dosyalar=dosyalar)
    except Durduruldu:
        emit("is_durduruldu")
    except Exception as e:  # noqa: BLE001 — hatayı arayüze göster
        mesaj = str(e)
        try:
            import anthropic

            if isinstance(e, anthropic.APIStatusError) and isinstance(e.body, dict):
                mesaj = f"Claude API {e.status_code}: {e.body.get('error', {}).get('message', mesaj)}"
        except ImportError:
            pass
        emit("is_hatasi", mesaj=mesaj or e.__class__.__name__)
    finally:
        is_.calisiyor = False
        is_.klasor.mkdir(parents=True, exist_ok=True)
        meta = {"id": is_.id, "talep": is_.talep, "simulasyon": simulasyon, "olaylar": is_.olaylar}
        (is_.klasor / "is.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


@app.post("/api/gorev")
def gorev_ver(istek: GorevIstegi) -> dict:
    if not istek.simulasyon and not _api_anahtari_var():
        raise HTTPException(400, "ANTHROPIC_API_KEY tanımlı değil. .env dosyasına yazın ya da simülasyon modunu açın.")
    office = load_office()
    if not office.aktif_calisanlar():
        raise HTTPException(400, "Ofiste aktif çalışan yok.")
    is_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    is_ = Is(id=is_id, talep=istek.talep.strip(), klasor=CIKTI / is_id)
    with yayin.kilit:
        if yayin.is_ and yayin.is_.calisiyor:
            raise HTTPException(409, "CEO şu anda başka bir iş üzerinde çalışıyor.")
        yayin.is_ = is_
    yayin.yayinla(is_, "is_basladi", talep=is_.talep, simulasyon=istek.simulasyon)
    threading.Thread(
        target=_isi_yurut, args=(is_, office, istek.simulasyon, istek.max_revizyon), daemon=True
    ).start()
    return {"is_id": is_id}


@app.post("/api/durdur")
def durdur() -> dict:
    if yayin.is_ and yayin.is_.calisiyor:
        yayin.is_.iptal.set()
        return {"durum": "durduruluyor"}
    return {"durum": "calisan is yok"}


@app.get("/api/olaylar")
async def olaylar(request: Request) -> StreamingResponse:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    with yayin.kilit:
        gecmis = list(yayin.is_.olaylar) if yayin.is_ else []
        yayin.aboneler.append((loop, q))

    async def akis():
        try:
            for o in gecmis:
                yield f"data: {json.dumps({**o, 'tekrar': True}, ensure_ascii=False)}\n\n"
            while not await request.is_disconnected():
                try:
                    o = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(o, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            with yayin.kilit:
                yayin.aboneler.remove((loop, q))

    return StreamingResponse(akis(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/gecmis")
def gecmis() -> list[dict]:
    if not CIKTI.exists():
        return []
    sonuc = []
    for d in sorted(CIKTI.iterdir(), reverse=True):
        meta = d / "is.json"
        if d.is_dir() and meta.exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            son = m["olaylar"][-1]["tip"] if m.get("olaylar") else ""
            sonuc.append({"id": d.name, "talep": m.get("talep", ""), "simulasyon": m.get("simulasyon"), "durum": son})
    return sonuc[:30]


@app.get("/api/is/{is_id}")
def is_detay(is_id: str) -> dict:
    klasor = (CIKTI / is_id).resolve()
    if klasor.parent != CIKTI or not (klasor / "is.json").exists():
        raise HTTPException(404, "İş bulunamadı.")
    m = json.loads((klasor / "is.json").read_text(encoding="utf-8"))
    m["dosyalar"] = sorted(str(p.relative_to(klasor)) for p in klasor.rglob("*") if p.is_file())
    return m


@app.get("/api/dosya", response_class=PlainTextResponse)
def dosya(yol: str) -> str:
    hedef = (CIKTI / yol).resolve()
    if CIKTI not in hedef.parents or not hedef.is_file():
        raise HTTPException(404, "Dosya bulunamadı.")
    try:
        return hedef.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "Metin olmayan dosya gösterilemiyor.")


app.mount("/static", StaticFiles(directory=WEB), name="static")


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    p = argparse.ArgumentParser(prog="plaza-ofis", description="Plaza'nın kuşbakışı ofis arayüzünü başlatır.")
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8770")))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--tarayici-acma", action="store_true", help="Tarayıcıyı otomatik açma")
    a = p.parse_args(argv)

    import uvicorn

    url = f"http://{a.host}:{a.port}"
    print(f"Plaza Ofis: {url}")
    if not a.tarayici_acma:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
