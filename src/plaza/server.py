"""Plaza Ofis: kuşbakışı ofis arayüzünü sunan yerel web sunucusu.

    uv run plaza-ofis            # http://127.0.0.1:8770 adresini açar
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import asyncio
import io
import json
import os
import shutil
import threading
import time
import uuid
import webbrowser
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .hatalar import turkce_mesaj
from .orchestrator import Durduruldu, IsAkisi
from .settings import (
    MAX_MASA,
    model_listesi,
    SAGLAYICILAR,
    anahtar_durumu,
    eksik_anahtarlar,
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
from . import zamanlayici
from .llm import llm_olustur
from .settings import (
    DEPARTMAN_SABLONLARI,
    TAHMINI_FIYAT,
    VARSAYILAN_FIYATLAR,
    genel_ayarlar,
    genel_ayarlari_kaydet,
    sablon_uygula,
)

WEB = Path(__file__).parent / "web"
CIKTI = Path(os.getenv("PLAZA_CIKTI", "cikti")).resolve()
MAX_EK_SAYISI = 10
MAX_EK_BOYUT = 200_000  # karakter


# ------------------------------------------------------------------ istekler
class Ek(BaseModel):
    ad: str = Field(min_length=1, max_length=120)
    icerik: str = Field(max_length=MAX_EK_BOYUT)


class GorevIstegi(BaseModel):
    talep: str = Field(min_length=1)
    simulasyon: bool = False
    max_revizyon: int = Field(default=1, ge=0, le=3)
    plan_onayi: bool = False
    onceki_is: str | None = None
    ekler: list[Ek] = Field(default_factory=list, max_length=MAX_EK_SAYISI)


# ------------------------------------------------------------------ durum
@dataclass
class Is:
    id: str
    istek: GorevIstegi
    klasor: Path
    olaylar: list[dict] = field(default_factory=list)
    calisiyor: bool = True
    iptal: threading.Event = field(default_factory=threading.Event)
    akis: IsAkisi | None = None
    baslangic: float = field(default_factory=time.time)
    devam: dict | None = None      # yarıda kalan işin kaydı (kaldığı yerden devam)
    kaynak: Path | None = None     # devam edilen işin klasörü (dosyaları kopyalanır)

    @property
    def talep(self) -> str:
        return self.istek.talep.strip()


class Yayin:
    """İş parçacığından gelen olayları SSE abonelerine iletir; iş kuyruğunu tutar."""

    def __init__(self) -> None:
        self.kilit = threading.Lock()
        self.aboneler: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self.is_: Is | None = None
        self.kuyruk: list[dict] = []  # {"id", "istek"}

    def _gonder(self, olay: dict) -> None:
        for loop, q in self.aboneler:
            loop.call_soon_threadsafe(q.put_nowait, olay)

    def yayinla(self, is_: Is, tip: str, **veri) -> None:
        olay = {"tip": tip, "zaman": time.time(), "is_id": is_.id, **veri}
        with self.kilit:
            is_.olaylar.append(olay)
            self._gonder(olay)

    def kuyruk_olayi(self) -> dict:
        return {
            "tip": "kuyruk", "zaman": time.time(),
            "liste": [{"id": k["id"], "talep": k["istek"].talep, "simulasyon": k["istek"].simulasyon}
                      for k in self.kuyruk],
        }

    def kuyrugu_yayinla(self) -> None:
        with self.kilit:
            self._gonder(self.kuyruk_olayi())

    def canli(self, is_: Is, masa: str, metin: str) -> None:
        """Çalışanın canlı yazdıkları: kaydedilmez, yalnızca açık sayfalara gider."""
        with self.kilit:
            self._gonder({"tip": "canli", "is_id": is_.id, "masa": masa, "metin": metin})


yayin = Yayin()


@asynccontextmanager
async def _yasam(_app):
    dur = zamanlayici.baslat(_zamanlanmisi_calistir)  # zamanlanmış görevleri izle
    yield
    dur.set()


app = FastAPI(title="Plaza Ofis", lifespan=_yasam)


@app.middleware("http")
async def _onbellek_yok(request: Request, call_next):
    """Arayüz dosyaları her açılışta tazelensin (güncellemeden sonra eski JS/CSS kalmasın)."""
    yanit = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        yanit.headers["Cache-Control"] = "no-cache"
    return yanit


def _api_anahtari_var() -> bool:
    return any(anahtar_durumu().values())


def _is_klasoru(is_id: str) -> Path:
    klasor = (CIKTI / is_id).resolve()
    if klasor.parent != CIKTI or not (klasor / "is.json").exists():
        raise HTTPException(404, "İş bulunamadı.")
    return klasor


# ------------------------------------------------------------------ ofis
@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/ofis")
def ofis() -> dict:
    return {
        **load_office().to_dict(),
        "modeller": model_listesi(),
        "araclar": list(TOOL_TYPES),
        "api_anahtari": _api_anahtari_var(),
        "saglayicilar": {k: {"ad": v["ad"], "anahtarlar": v["anahtarlar"], "hazir": anahtar_durumu()[k]}
                         for k, v in SAGLAYICILAR.items()},
        "max_masa": MAX_MASA,
        "genel": genel_ayarlar(),
        "varsayilan_fiyatlar": VARSAYILAN_FIYATLAR,
        "tahmini_fiyat": sorted(TAHMINI_FIYAT),
        "sablonlar": {k: {"ad": v["ad"], "aciklama": v["aciklama"], "calisan": len(v["calisanlar"])}
                      for k, v in DEPARTMAN_SABLONLARI.items()},
    }


class MasaAyari(BaseModel):
    isim: str | None = None
    model: str | None = None
    yedek_model: str | None = None
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
    yedek_model: str = ""
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


@app.post("/api/sablon/{sablon_id}")
def sablon_ekle(sablon_id: str) -> dict:
    return _degistir(sablon_uygula, sablon_id)


class GenelAyarlar(BaseModel):
    hiz: dict[str, int] | None = None
    fiyatlar: dict[str, list[float] | None] | None = None
    canli_akis: bool | None = None


@app.put("/api/genel")
def genel_kaydet(ayar: GenelAyarlar) -> dict:
    try:
        genel_ayarlari_kaydet(ayar.model_dump(exclude_none=True))
    except (ValueError, TypeError, IndexError) as e:
        raise HTTPException(400, f"Geçersiz ayar: {e}")
    return ofis()


# ------------------------------------------------------------------ masayla sohbet
class SohbetMesaji(BaseModel):
    rol: str = Field(pattern="^(kullanici|asistan)$")
    icerik: str = Field(min_length=1, max_length=20000)


class SohbetIstegi(BaseModel):
    mesajlar: list[SohbetMesaji] = Field(min_length=1, max_length=40)


@app.post("/api/sohbet/{key}")
def sohbet(key: str, istek: SohbetIstegi) -> dict:
    """Bir çalışanla (ya da CEO ile) CEO akışı dışında doğrudan konuşma."""
    try:
        d = load_office().desk(key)
    except KeyError:
        raise HTTPException(404, "Böyle bir masa yok.")
    sistem = (f"Adın {d.isim}. Plaza'da {d.department} bölümünde {d.role} olarak çalışıyorsun. {d.goal}\n"
              f"{d.backstory}\nPatronun seninle doğrudan sohbet ediyor; kısa, net ve Türkçe yanıt ver.")
    mesajlar = [{"role": "system", "content": sistem}] + [
        {"role": "user" if m.rol == "kullanici" else "assistant", "content": m.icerik} for m in istek.mesajlar]
    from .orchestrator import _temizle

    son_hata = None
    for model in [d.model] + ([d.yedek_model] if d.yedek_model and d.yedek_model != d.model else []):
        try:
            return {"yanit": _temizle(str(llm_olustur(model).call(mesajlar))), "model": model}
        except Exception as e:  # noqa: BLE001 — yedek modeli dene, sonra Türkçe hata ver
            son_hata = e
    raise HTTPException(502, turkce_mesaj(son_hata))


# ------------------------------------------------------------------ zamanlanmış görevler
class ZamanlanmisGorev(BaseModel):
    talep: str | None = None
    saat: str | None = None
    gunler: list[int] | None = None
    simulasyon: bool | None = None
    aktif: bool | None = None


def _zamanlanmisi_calistir(kayit: dict) -> str:
    try:
        r = gorevi_al(GorevIstegi(talep=kayit["talep"], simulasyon=kayit.get("simulasyon", False)))
    except HTTPException as e:
        return f"başlatılamadı: {e.detail}"
    return f"sıraya alındı ({r['sira']}. sıra)" if r.get("kuyrukta") else f"başlatıldı ({r['is_id']})"


@app.get("/api/zamanlanmis")
def zamanlanmis_listesi() -> list[dict]:
    return zamanlayici.listele()


@app.post("/api/zamanlanmis")
def zamanlanmis_ekle(g: ZamanlanmisGorev) -> list[dict]:
    try:
        zamanlayici.ekle(g.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return zamanlayici.listele()


@app.put("/api/zamanlanmis/{zid}")
def zamanlanmis_guncelle(zid: str, g: ZamanlanmisGorev) -> list[dict]:
    try:
        zamanlayici.guncelle(zid, g.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(404, "Bulunamadı.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return zamanlayici.listele()


@app.delete("/api/zamanlanmis/{zid}")
def zamanlanmis_sil(zid: str) -> list[dict]:
    try:
        zamanlayici.sil(zid)
    except KeyError:
        raise HTTPException(404, "Bulunamadı.")
    return zamanlayici.listele()


@app.post("/api/ofis/sifirla")
def ofis_sifirla() -> dict:
    return _degistir(ofisi_sifirla)


# ------------------------------------------------------------------ işler
def _yeni_is(istek: GorevIstegi, devam: dict | None = None, kaynak: Path | None = None) -> Is:
    """Kilit altında çağrılır."""
    taban = datetime.now().strftime("%Y%m%d-%H%M%S")
    is_id, i = taban, 2
    while (CIKTI / is_id).exists() or (yayin.is_ and yayin.is_.id == is_id):
        is_id, i = f"{taban}-{i}", i + 1
    return Is(id=is_id, istek=istek, klasor=CIKTI / is_id, devam=devam, kaynak=kaynak)


def _baslat(is_: Is) -> None:
    istek = is_.istek
    if is_.kaynak and is_.kaynak.exists():  # kaldığı yerden: önceki denemenin dosyalarıyla başla
        shutil.copytree(is_.kaynak, is_.klasor, ignore=shutil.ignore_patterns("is.json"), dirs_exist_ok=True)
    is_.klasor.mkdir(parents=True, exist_ok=True)
    ekler = []
    for ek in istek.ekler:
        ad = Path(ek.ad).name or "ek.txt"
        (is_.klasor / "girdi").mkdir(exist_ok=True)
        (is_.klasor / "girdi" / ad).write_text(ek.icerik, encoding="utf-8")
        ekler.append((ad, ek.icerik))
    onceki_sonuc = ""
    if istek.onceki_is:
        onceki = (CIKTI / istek.onceki_is).resolve()
        if onceki.parent == CIKTI and (onceki / "SONUC.md").exists():
            onceki_sonuc = (onceki / "SONUC.md").read_text(encoding="utf-8")
            shutil.copytree(onceki, is_.klasor / "onceki", ignore=shutil.ignore_patterns("is.json", "onceki"))
    yayin.yayinla(
        is_, "is_basladi", talep=is_.talep, simulasyon=istek.simulasyon, plan_onayi=istek.plan_onayi,
        onceki_is=istek.onceki_is if onceki_sonuc else None, ekler=[a for a, _ in ekler],
        devam_edilen=is_.kaynak.name if is_.devam and is_.kaynak else None,
    )
    threading.Thread(target=_isi_yurut, args=(is_, load_office(), ekler, onceki_sonuc), daemon=True).start()


def _isi_yurut(is_: Is, office, ekler, onceki_sonuc: str) -> None:
    istek = is_.istek

    def emit(tip: str, **veri) -> None:
        yayin.yayinla(is_, tip, **veri)

    akis = IsAkisi(
        office, is_.talep, emit, is_.klasor, istek.simulasyon, istek.max_revizyon, is_.iptal,
        plan_onayi=istek.plan_onayi and not is_.devam, onceki_sonuc=onceki_sonuc, ekler=ekler,
        devam=is_.devam, canli=lambda masa, metin: yayin.canli(is_, masa, metin),
    )
    is_.akis = akis
    try:
        sonuc = akis.calistir()
        (is_.klasor / "SONUC.md").write_text(sonuc, encoding="utf-8")
        dosyalar = sorted(str(p.relative_to(is_.klasor)) for p in is_.klasor.rglob("*") if p.is_file())
        emit("is_bitti", sonuc=sonuc, klasor=is_.klasor.name, dosyalar=dosyalar,
             istatistik={**akis.ozet_istatistik(), "sure": round(time.time() - is_.baslangic, 1)})
    except Durduruldu:
        emit("is_durduruldu")
    except Exception as e:  # noqa: BLE001 — hatayı arayüze göster
        masa = getattr(e, "plaza_masa", None)
        mesaj = turkce_mesaj(e)
        emit("is_hatasi", mesaj=f"{masa}: {mesaj}" if masa else mesaj,
             ayrinti=(str(e) or e.__class__.__name__)[:600])
    finally:
        is_.klasor.mkdir(parents=True, exist_ok=True)
        meta = {"id": is_.id, "talep": is_.talep, "simulasyon": istek.simulasyon, "olaylar": is_.olaylar,
                "istek": istek.model_dump(), "kayit": akis.kayit()}
        (is_.klasor / "is.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        with yayin.kilit:
            is_.calisiyor = False
            sonraki = None
            if yayin.kuyruk:
                k = yayin.kuyruk.pop(0)
                sonraki = _yeni_is(k["istek"], k.get("devam"), k.get("kaynak"))
                yayin.is_ = sonraki
        if sonraki:
            yayin.kuyrugu_yayinla()
            _baslat(sonraki)


def gorevi_al(istek: GorevIstegi, devam: dict | None = None, kaynak: Path | None = None) -> dict:
    """Görevi hemen başlatır ya da CEO meşgulse sıraya koyar (arayüz ve zamanlayıcı kullanır)."""
    office = load_office()
    if not office.aktif_calisanlar():
        raise HTTPException(400, "Ofiste aktif çalışan yok.")
    if not istek.simulasyon:
        eksik = eksik_anahtarlar(office)
        if eksik:
            raise HTTPException(
                400,
                "Şu masaların yapay zekâsı hazır değil — eksikleri giderin, masanın modelini değiştirin "
                "ya da simülasyonu açın: " + "; ".join(eksik),
            )
    if istek.onceki_is:
        _is_klasoru(istek.onceki_is)
    with yayin.kilit:
        if yayin.is_ and yayin.is_.calisiyor:
            kid = uuid.uuid4().hex[:8]
            yayin.kuyruk.append({"id": kid, "istek": istek, "devam": devam, "kaynak": kaynak})
            sira = len(yayin.kuyruk)
            is_ = None
        else:
            is_ = _yeni_is(istek, devam, kaynak)
            yayin.is_ = is_
    if is_ is None:
        yayin.kuyrugu_yayinla()
        return {"kuyrukta": True, "id": kid, "sira": sira}
    _baslat(is_)
    return {"is_id": is_.id}


@app.post("/api/gorev")
def gorev_ver(istek: GorevIstegi) -> dict:
    return gorevi_al(istek)


@app.post("/api/is/{is_id}/devam")
def isi_devam_ettir(is_id: str) -> dict:
    """Hata veren ya da durdurulan bir işi, biten adımları yeniden yapmadan sürdürür."""
    klasor = _is_klasoru(is_id)
    m = json.loads((klasor / "is.json").read_text(encoding="utf-8"))
    son = m["olaylar"][-1]["tip"] if m.get("olaylar") else ""
    if son not in ("is_hatasi", "is_durduruldu"):
        raise HTTPException(400, "Yalnızca hata veren ya da durdurulan işler sürdürülebilir.")
    kayit = m.get("kayit") or {}
    if not kayit.get("adimlar") or "istek" not in m:
        raise HTTPException(400, "Bu iş plan aşamasını geçmeden durmuş; yeniden başlatmak gerekiyor.")
    return gorevi_al(GorevIstegi(**m["istek"]), devam=kayit, kaynak=klasor)


@app.delete("/api/kuyruk/{kid}")
def kuyruktan_cikar(kid: str) -> dict:
    with yayin.kilit:
        yayin.kuyruk = [k for k in yayin.kuyruk if k["id"] != kid]
    yayin.kuyrugu_yayinla()
    return {"durum": "tamam"}


class PlanOnayi(BaseModel):
    adimlar: list[dict]


@app.post("/api/plan/onay")
def plan_onayla(onay: PlanOnayi) -> dict:
    is_ = yayin.is_
    if not is_ or not is_.calisiyor or not is_.akis or not is_.akis.onay_bekliyor:
        raise HTTPException(409, "Onay bekleyen bir plan yok.")
    try:
        is_.akis.plani_onayla(onay.adimlar)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"durum": "onaylandi"}


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
        gecmis.append(yayin.kuyruk_olayi())
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


# ------------------------------------------------------------------ geçmiş
def _metalar():
    if not CIKTI.exists():
        return
    for d in sorted(CIKTI.iterdir(), reverse=True):
        meta = d / "is.json"
        if d.is_dir() and meta.exists():
            try:
                yield d, json.loads(meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue


@app.get("/api/gecmis")
def gecmis() -> list[dict]:
    sonuc = []
    for d, m in _metalar():
        son = m["olaylar"][-1]["tip"] if m.get("olaylar") else ""
        sonuc.append({"id": d.name, "talep": m.get("talep", ""), "simulasyon": m.get("simulasyon"), "durum": son})
        if len(sonuc) >= 30:
            break
    return sonuc


@app.get("/api/istatistik")
def istatistik() -> dict:
    """Masa bazında tüm geçmiş işlerin toplamı (simülasyonlar hariç)."""
    masalar: dict[str, dict] = {}
    is_sayisi = 0
    for _, m in _metalar():
        if m.get("simulasyon"):
            continue
        is_sayisi += 1
        for o in m.get("olaylar", []):
            if o.get("tip") == "gorev_bitti":
                s = masalar.setdefault(o["kime"], {"gorev": 0, "sure": 0.0, "token": 0})
                s["gorev"] += 1
                s["sure"] = round(s["sure"] + o.get("sure", 0), 1)
                s["token"] += o.get("token", 0)
            elif o.get("tip") == "is_bitti":
                s = masalar.setdefault("ceo", {"gorev": 0, "sure": 0.0, "token": 0})
                s["gorev"] += 1
                s["sure"] = round(s["sure"] + o.get("istatistik", {}).get("sure", 0), 1)
                s["token"] += o.get("istatistik", {}).get("ceo_token", 0)
    return {"is_sayisi": is_sayisi, "masalar": masalar, "projeler": _basarili_projeler(),
            "harcama": _harcama()}


def _harcama() -> dict:
    """Ay ay toplam maliyet (USD). Fiyatı bilinmeyen modellerin kullanımı varsa 'eksik' işaretlenir."""
    aylar: dict[str, float] = {}
    eksik = False
    for d, m in _metalar():
        if m.get("simulasyon"):
            continue
        ay = f"{d.name[:4]}-{d.name[4:6]}"
        toplam = 0.0
        for o in m.get("olaylar", []):
            if o.get("tip") == "gorev_bitti" and o.get("token"):
                if o.get("maliyet") is None:
                    eksik = True
                else:
                    toplam += o["maliyet"]
            elif o.get("tip") == "is_bitti":
                ist = o.get("istatistik", {})
                toplam += ist.get("ceo_maliyet") or 0.0
                eksik = eksik or bool(ist.get("maliyet_eksik"))
        aylar[ay] = round(aylar.get(ay, 0.0) + toplam, 6)
    bu_ay = datetime.now().strftime("%Y-%m")
    return {"bu_ay": aylar.get(bu_ay, 0.0), "aylar": dict(sorted(aylar.items(), reverse=True)), "eksik": eksik}


def _basarili_projeler() -> dict[str, list[dict]]:
    """Departman başına başarıyla biten (gerçek) projeler. 'ceo': tüm başarılı projeler.

    Bir proje, o departmandan en az bir çalışan görevini tamamladıysa departmana sayılır.
    Masa → departman eşlemesi ofisin şu anki düzenine göre yapılır.
    """
    office = load_office()
    masa_dep = {s.key: d.key for d in office.departments for s in d.staff}
    sonuc: dict[str, list[dict]] = {"ceo": [], **{d.key: [] for d in office.departments}}
    for d, m in _metalar():
        olaylar = m.get("olaylar", [])
        if m.get("simulasyon") or not any(o.get("tip") == "is_bitti" for o in olaylar):
            continue
        proje = {"id": d.name, "talep": m.get("talep", "")}
        sonuc["ceo"].append(proje)
        for dep in {masa_dep[o["kime"]] for o in olaylar if o.get("tip") == "gorev_bitti" and o.get("kime") in masa_dep}:
            sonuc[dep].append(proje)
    return sonuc


@app.get("/api/is/{is_id}")
def is_detay(is_id: str) -> dict:
    klasor = _is_klasoru(is_id)
    m = json.loads((klasor / "is.json").read_text(encoding="utf-8"))
    m["dosyalar"] = sorted(str(p.relative_to(klasor)) for p in klasor.rglob("*") if p.is_file())
    return m


@app.get("/api/is/{is_id}/zip")
def is_zip(is_id: str) -> Response:
    klasor = _is_klasoru(is_id)
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        for p in klasor.rglob("*"):
            if p.is_file():
                z.write(p, f"{is_id}/{p.relative_to(klasor)}")
    return Response(
        tampon.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="plaza-{is_id}.zip"'},
    )


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
