"""Ofis yapılandırması: departments.yaml + masa bazlı kullanıcı ayarları (ofis.json).

Arayüzden bir masaya tıklayıp yapılan değişiklikler (model, rol, hedef, araçlar…)
ofis.json dosyasına yazılır; YAML dosyası olduğu gibi kalır.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .office import DEFAULT_MODEL, load_org
from .tools import TOOL_TYPES

AYAR_DOSYASI = Path(os.getenv("PLAZA_OFIS_AYAR", "ofis.json"))
DUZENLENEBILIR = {"isim", "model", "yedek_model", "role", "goal", "backstory", "tools", "aktif"}

# Sağlayıcılar: model kimliğinin öneki → gereken ortam değişkeni(leri)
SAGLAYICILAR = {
    "anthropic": {"ad": "Anthropic (Claude)", "anahtarlar": ["ANTHROPIC_API_KEY"]},
    "google": {"ad": "Google (Gemini)", "anahtarlar": ["GOOGLE_API_KEY", "GEMINI_API_KEY"]},
    "deepseek": {"ad": "DeepSeek (bulut API)", "anahtarlar": ["DEEPSEEK_API_KEY"]},
    "yerel": {"ad": "Yerel — Ollama (API'siz, ücretsiz)", "anahtarlar": []},
}
_ONEK = {
    "anthropic": "anthropic", "claude": "anthropic", "gemini": "google", "google": "google",
    "deepseek": "deepseek", "ollama": "yerel", "ollama_chat": "yerel",
}

MODELLER = [
    {"id": "anthropic/claude-opus-5-5", "ad": "Claude Opus 5.5", "kisa": "Opus 5.5", "saglayici": "anthropic"},
    {"id": "anthropic/claude-sonnet-5-5", "ad": "Claude Sonnet 5.5", "kisa": "Sonnet 5.5", "saglayici": "anthropic"},
    {"id": "anthropic/claude-haiku-5-5", "ad": "Claude Haiku 5.5", "kisa": "Haiku 5.5", "saglayici": "anthropic"},
    {"id": "anthropic/claude-fable-5-1", "ad": "Claude Fable 5.1", "kisa": "Fable 5.1", "saglayici": "anthropic"},
    {"id": "gemini/gemini-4-carbon", "ad": "Gemini 4 Carbon", "kisa": "Gemini 4 Carbon", "saglayici": "google"},
    {"id": "gemini/gemini-4-argon", "ad": "Gemini 4 Argon", "kisa": "Gemini 4 Argon", "saglayici": "google"},
    {"id": "gemini/gemini-3.8-flash", "ad": "Gemini 3.8 Flash", "kisa": "Gemini 3.8 Flash", "saglayici": "google"},
    {"id": "gemini/gemini-3.5-flash-lite", "ad": "Gemini 3.5 Flash-Lite", "kisa": "Gemini Flash-Lite", "saglayici": "google"},
    {"id": "deepseek/deepseek-v4-pro", "ad": "DeepSeek V4 Pro", "kisa": "DeepSeek V4 Pro", "saglayici": "deepseek"},
    {"id": "deepseek/deepseek-flash", "ad": "DeepSeek Flash", "kisa": "DeepSeek Flash", "saglayici": "deepseek"},
    # Bu bilgisayarda Ollama ile çalışan, API anahtarı gerektirmeyen modeller
    {"id": "ollama/deepseek-r1:8b", "ad": "DeepSeek R1 8B (5.2 GB)", "kisa": "DeepSeek R1 8B · yerel",
     "saglayici": "yerel"},
    {"id": "ollama/deepseek-r1:14b", "ad": "DeepSeek R1 14B (9 GB, daha yavaş)", "kisa": "DeepSeek R1 14B · yerel",
     "saglayici": "yerel"},
]


# ------------------------------------------------------------- yerel (Ollama)
def _ollama_adresi() -> str:
    adres = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")
    if not adres.startswith("http"):
        adres = "http://" + adres
    return adres.removesuffix("/v1")


_ollama_onbellek: dict[str, tuple[float, object]] = {}


def _ollama(yol: str, veri: dict | None = None, sure: float = 5.0):
    """Ollama'ya kısa bir istek; çalışmıyorsa None. Sonuç birkaç saniye önbelleklenir."""
    anahtar = yol + json.dumps(veri or {}, sort_keys=True)
    simdi = time.monotonic()
    if anahtar in _ollama_onbellek and simdi - _ollama_onbellek[anahtar][0] < sure:
        return _ollama_onbellek[anahtar][1]
    try:
        istek = urllib.request.Request(
            _ollama_adresi() + yol,
            data=json.dumps(veri).encode() if veri is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(istek, timeout=1.5) as r:
            sonuc = json.loads(r.read())
    except (OSError, ValueError):
        sonuc = None
    _ollama_onbellek[anahtar] = (simdi, sonuc)
    return sonuc


def ollama_modelleri() -> list[str] | None:
    """Kurulu Ollama modelleri; Ollama çalışmıyorsa None."""
    veri = _ollama("/api/tags")
    return None if veri is None else [m["name"] for m in veri.get("models", [])]


def _ollama_adi(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def ollama_kurulu_mu(model: str, kurulu: list[str] | None = None) -> bool:
    kurulu = ollama_modelleri() if kurulu is None else kurulu
    ad = _ollama_adi(model)
    return bool(kurulu) and (ad in kurulu or f"{ad}:latest" in kurulu)


def arac_destekli(model: str) -> bool:
    """Model dosya araçlarını (function calling) kullanabilir mi? Bulut modelleri: evet."""
    if saglayici(model) != "yerel":
        return True
    bilgi = _ollama("/api/show", {"model": _ollama_adi(model)}, sure=300)
    return bool(bilgi) and "tools" in bilgi.get("capabilities", [])


def model_listesi() -> list[dict]:
    """Hazır modeller + Ollama'da kurulu olup listede olmayanlar; yerel modeller için 'kurulu' bilgisi."""
    kurulu = ollama_modelleri()
    liste = [dict(m) for m in MODELLER]
    for m in liste:
        if m["saglayici"] == "yerel":
            m["kurulu"] = ollama_kurulu_mu(m["id"], kurulu)
    bilinen = {_ollama_adi(m["id"]) for m in liste if m["saglayici"] == "yerel"}
    for ad in kurulu or []:
        if ad not in bilinen and ad.removesuffix(":latest") not in bilinen:
            liste.append({"id": f"ollama/{ad}", "ad": f"{ad} (kurulu)", "kisa": f"{ad} · yerel",
                          "saglayici": "yerel", "kurulu": True})
    return liste


# ------------------------------------------------------------- hazırlık
def saglayici(model: str) -> str | None:
    """'gemini/gemini-4-argon' → 'google'. Bilinmeyen önek için None."""
    onek = model.split("/", 1)[0].lower() if "/" in model else ("anthropic" if model.startswith("claude-") else "")
    return _ONEK.get(onek)


def anahtar_var(saglayici_adi: str) -> bool:
    if saglayici_adi == "yerel":
        return ollama_modelleri() is not None  # anahtar gerekmez; Ollama çalışıyor mu?
    return any(os.getenv(k, "").strip() for k in SAGLAYICILAR[saglayici_adi]["anahtarlar"])


def anahtar_durumu() -> dict[str, bool]:
    return {s: anahtar_var(s) for s in SAGLAYICILAR}


def eksik_anahtarlar(office: "Office") -> list[str]:
    """Aktif masaların (ve CEO'nun) modellerini çalıştırmak için eksik olanlar."""
    eksik = []
    for d in [office.ceo, *office.aktif_calisanlar()]:
        s = saglayici(d.model)
        if not s:
            continue
        if s == "yerel":
            if ollama_modelleri() is None:
                mesaj = f"{d.isim}: Ollama çalışmıyor (sudo systemctl start ollama)"
            elif not ollama_kurulu_mu(d.model):
                mesaj = f"{d.isim}: '{_ollama_adi(d.model)}' modeli indirilmemiş (ollama pull {_ollama_adi(d.model)})"
            else:
                continue
        elif not anahtar_var(s):
            mesaj = f"{d.isim} ({SAGLAYICILAR[s]['ad']}): {' veya '.join(SAGLAYICILAR[s]['anahtarlar'])} yok"
        else:
            continue
        if mesaj not in eksik:
            eksik.append(mesaj)
    return eksik


MAX_MASA = 6  # bir odaya sığan masa sayısı

# ofis.json içindeki özel bölümler (masa anahtarlarıyla çakışmaz)
EK_DEP = "_ek_departmanlar"      # {dkey: {"name"}}
EK_CALISAN = "_ek_calisanlar"    # {key: {"department_key", "isim", "role", "goal", "backstory", "tools", "model"}}
GIZLI = "_gizli"                 # YAML'dan gelip kaldırılan departman/çalışan anahtarları
DEP_ADLARI = "_departman_adlari"  # {dkey: yeni ad}

_kilit = threading.Lock()
_TR = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")


@dataclass
class Desk:
    key: str
    department_key: str
    department: str
    isim: str
    role: str
    goal: str
    backstory: str
    model: str
    tools: list[str] = field(default_factory=list)
    aktif: bool = True
    yedek_model: str = ""  # ana model kalıcı hata verirse devralan model (isteğe bağlı)
    ozel: bool = False  # ofis.json'da kullanıcı ayarı var mı
    eklenen: bool = False  # arayüzden eklenmiş masa mı


@dataclass
class Department:
    key: str
    name: str
    staff: list[Desk]
    eklenen: bool = False  # arayüzden eklenmiş departman mı


@dataclass
class Office:
    ceo: Desk
    departments: list[Department]

    def calisanlar(self) -> list[Desk]:
        return [s for d in self.departments for s in d.staff]

    def aktif_calisanlar(self) -> list[Desk]:
        return [s for s in self.calisanlar() if s.aktif]

    def desk(self, key: str) -> Desk:
        if key == "ceo":
            return self.ceo
        for s in self.calisanlar():
            if s.key == key:
                return s
        raise KeyError(key)

    def to_dict(self) -> dict:
        return {
            "ceo": asdict(self.ceo),
            "departmanlar": [
                {"key": d.key, "name": d.name, "eklenen": d.eklenen, "staff": [asdict(s) for s in d.staff]}
                for d in self.departments
            ],
        }


def _ayarlari_oku(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _uygula(desk: Desk, ayar: dict | None) -> Desk:
    if ayar:
        for k, v in ayar.items():
            if k in DUZENLENEBILIR:
                setattr(desk, k, v)
        desk.ozel = True
    return desk


def load_office(org_file: Path | None = None, ayar_dosyasi: Path = AYAR_DOSYASI) -> Office:
    org = load_org(org_file)
    ayar = _ayarlari_oku(ayar_dosyasi)
    plaza_model = os.getenv("PLAZA_MODEL", DEFAULT_MODEL)
    ceo_model = os.getenv("PLAZA_MANAGER_MODEL", plaza_model)
    staff_model = os.getenv("PLAZA_STAFF_MODEL", plaza_model)

    m = org["manager"]
    ceo = _uygula(
        Desk(
            key="ceo", department_key="ceo", department="Yönetim",
            isim=m.get("isim", "CEO"), role=m["role"], goal=m["goal"].strip(),
            backstory=m["backstory"].strip(), model=ceo_model,
        ),
        ayar.get("ceo"),
    )
    gizli = set(ayar.get(GIZLI, []))
    adlar = ayar.get(DEP_ADLARI, {})
    ham: dict[str, dict] = {}  # dkey -> {"name", "staff": [...], "ozel"}
    for dkey, d in org["departments"].items():
        ham[dkey] = {"name": d["name"], "staff": list(d["staff"]), "ozel": False}
    for dkey, d in ayar.get(EK_DEP, {}).items():
        ham[dkey] = {"name": d["name"], "staff": [], "ozel": True}
    for key, c in ayar.get(EK_CALISAN, {}).items():
        if c.get("department_key") in ham:
            ham[c["department_key"]]["staff"].append({**c, "key": key, "_ozel": True})

    departments = []
    for dkey, d in ham.items():
        if dkey in gizli:
            continue
        ad = adlar.get(dkey, d["name"])
        staff = [
            _uygula(
                Desk(
                    key=s["key"], department_key=dkey, department=ad,
                    isim=s.get("isim") or s["role"], role=s["role"], goal=(s.get("goal") or "").strip(),
                    backstory=(s.get("backstory") or "").strip(), model=s.get("model") or staff_model,
                    tools=list(s.get("tools", [])), eklenen=bool(s.get("_ozel")),
                    yedek_model=s.get("yedek_model") or "",
                ),
                ayar.get(s["key"]),
            )
            for s in d["staff"]
            if s["key"] not in gizli
        ]
        departments.append(Department(key=dkey, name=ad, staff=staff, eklenen=d["ozel"]))
    return Office(ceo=ceo, departments=departments)


def masa_ayari_kaydet(key: str, degerler: dict, ayar_dosyasi: Path = AYAR_DOSYASI) -> None:
    temiz = {k: v for k, v in degerler.items() if k in DUZENLENEBILIR}
    if "tools" in temiz:
        bilinmeyen = set(temiz["tools"]) - TOOL_TYPES.keys()
        if bilinmeyen:
            raise ValueError(f"Bilinmeyen araç: {', '.join(sorted(bilinmeyen))}")
    if "model" in temiz and not str(temiz["model"]).strip():
        raise ValueError("Model boş olamaz.")
    with _kilit:
        ayar = _ayarlari_oku(ayar_dosyasi)
        ayar.setdefault(key, {}).update(temiz)
        ayar_dosyasi.write_text(json.dumps(ayar, ensure_ascii=False, indent=2), encoding="utf-8")


def masa_ayarini_sil(key: str, ayar_dosyasi: Path = AYAR_DOSYASI) -> None:
    with _kilit:
        ayar = _ayarlari_oku(ayar_dosyasi)
        if ayar.pop(key, None) is not None:
            ayar_dosyasi.write_text(json.dumps(ayar, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------- departman/masa ekleme
def _yaz(ayar: dict, ayar_dosyasi: Path) -> None:
    ayar_dosyasi.write_text(json.dumps(ayar, ensure_ascii=False, indent=2), encoding="utf-8")


def _anahtar_uret(metin: str, kullanilan: set[str]) -> str:
    taban = "".join(c if c.isalnum() else "_" for c in metin.translate(_TR).lower()).strip("_")
    taban = "_".join(p for p in taban.split("_") if p)[:24] or "x"
    if taban[0].isdigit():
        taban = "d_" + taban
    key, i = taban, 2
    while key in kullanilan or key.startswith("_"):
        key, i = f"{taban}_{i}", i + 1
    return key


def _tum_anahtarlar(org: dict, ayar: dict) -> set[str]:
    k = {"ceo", *org["departments"], *ayar.get(EK_DEP, {}), *ayar.get(EK_CALISAN, {})}
    k |= {s["key"] for d in org["departments"].values() for s in d["staff"]}
    return k


def departman_ekle(name: str, ayar_dosyasi: Path = AYAR_DOSYASI) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Departman adı boş olamaz.")
    with _kilit:
        ayar = _ayarlari_oku(ayar_dosyasi)
        key = _anahtar_uret(name, _tum_anahtarlar(load_org(), ayar))
        ayar.setdefault(EK_DEP, {})[key] = {"name": name}
        _yaz(ayar, ayar_dosyasi)
    return key


def departman_adlandir(dkey: str, name: str, ayar_dosyasi: Path = AYAR_DOSYASI) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Departman adı boş olamaz.")
    with _kilit:
        ayar = _ayarlari_oku(ayar_dosyasi)
        if dkey in ayar.get(EK_DEP, {}):
            ayar[EK_DEP][dkey]["name"] = name
        else:
            ayar.setdefault(DEP_ADLARI, {})[dkey] = name
        _yaz(ayar, ayar_dosyasi)


def departman_kaldir(dkey: str, ayar_dosyasi: Path = AYAR_DOSYASI) -> None:
    with _kilit:
        ayar = _ayarlari_oku(ayar_dosyasi)
        if dkey in ayar.get(EK_DEP, {}):
            del ayar[EK_DEP][dkey]
            for key in [k for k, c in ayar.get(EK_CALISAN, {}).items() if c.get("department_key") == dkey]:
                del ayar[EK_CALISAN][key]
                ayar.pop(key, None)
        elif dkey in load_org()["departments"]:
            ayar.setdefault(GIZLI, [])
            if dkey not in ayar[GIZLI]:
                ayar[GIZLI].append(dkey)
        else:
            raise KeyError(dkey)
        _yaz(ayar, ayar_dosyasi)


def masa_ekle(dkey: str, degerler: dict, ayar_dosyasi: Path = AYAR_DOSYASI) -> str:
    office = load_office(ayar_dosyasi=ayar_dosyasi)
    dep = next((d for d in office.departments if d.key == dkey), None)
    if dep is None:
        raise KeyError(dkey)
    if len(dep.staff) >= MAX_MASA:
        raise ValueError(f"Bir odaya en fazla {MAX_MASA} masa sığar.")
    role = str(degerler.get("role", "")).strip()
    if not role:
        raise ValueError("Rol boş olamaz.")
    tools = list(degerler.get("tools") or [])
    if set(tools) - TOOL_TYPES.keys():
        raise ValueError("Bilinmeyen araç.")
    with _kilit:
        ayar = _ayarlari_oku(ayar_dosyasi)
        key = _anahtar_uret(role, _tum_anahtarlar(load_org(), ayar))
        ayar.setdefault(EK_CALISAN, {})[key] = {
            "department_key": dkey,
            "isim": str(degerler.get("isim", "")).strip() or role,
            "role": role,
            "goal": str(degerler.get("goal", "")).strip() or f"{role} olarak kendisine verilen görevleri eksiksiz yapmak.",
            "backstory": str(degerler.get("backstory", "")).strip() or f"Deneyimli bir {role.lower()}sın.",
            "tools": tools,
            "model": str(degerler.get("model", "")).strip() or None,
        }
        if degerler.get("yedek_model"):
            ayar[EK_CALISAN][key]["yedek_model"] = str(degerler["yedek_model"]).strip()
        _yaz(ayar, ayar_dosyasi)
    return key


def masa_kaldir(key: str, ayar_dosyasi: Path = AYAR_DOSYASI) -> None:
    if key == "ceo":
        raise ValueError("CEO masası kaldırılamaz.")
    with _kilit:
        ayar = _ayarlari_oku(ayar_dosyasi)
        ayar.pop(key, None)
        if key in ayar.get(EK_CALISAN, {}):
            del ayar[EK_CALISAN][key]
        elif any(s["key"] == key for d in load_org()["departments"].values() for s in d["staff"]):
            ayar.setdefault(GIZLI, [])
            if key not in ayar[GIZLI]:
                ayar[GIZLI].append(key)
        else:
            raise KeyError(key)
        _yaz(ayar, ayar_dosyasi)


def ofisi_sifirla(ayar_dosyasi: Path = AYAR_DOSYASI) -> None:
    with _kilit:
        ayar_dosyasi.unlink(missing_ok=True)


# ------------------------------------------------------------- genel ayarlar
GENEL = "_genel"

# Milyon token başına (giriş, çıkış) USD. Claude: Anthropic'in resmî fiyatları.
# Gemini ve DeepSeek: üçüncü taraf kaynaklardan tahmini (Kasım 2026); arayüzden düzeltilebilir.
# None = bilinmiyor (maliyet hesaplanmaz).
VARSAYILAN_FIYATLAR: dict[str, list[float] | None] = {
    "anthropic/claude-opus-5-5": [4.0, 20.0],
    "anthropic/claude-sonnet-5-5": [2.0, 10.0],
    "anthropic/claude-haiku-5-5": [0.10, 0.50],
    "anthropic/claude-fable-5-1": [10.0, 50.0],
    "gemini/gemini-4-carbon": None,
    "gemini/gemini-4-argon": [2.0, 10.0],
    "gemini/gemini-3.8-flash": [0.75, 3.75],
    "gemini/gemini-3.5-flash-lite": None,
    "deepseek/deepseek-v4-pro": [1.32, 3.96],
    "deepseek/deepseek-flash": [0.30, 1.20],
}
TAHMINI_FIYAT = {"gemini", "deepseek"}  # önek: bu sağlayıcıların fiyatları tahmini

VARSAYILAN_GENEL = {
    # Dakikadaki en fazla istek (0 = sınırsız). Google ücretsiz katmanı Flash-Lite için 15/dk.
    "hiz": {"anthropic": 0, "google": 12, "deepseek": 0, "yerel": 0},
    "fiyatlar": {},          # kullanıcının düzelttiği fiyatlar (model → [giriş, çıkış])
    "canli_akis": True,      # çalışanların yazdıkları canlı gösterilsin
}


def genel_ayarlar(ayar_dosyasi: Path | None = None) -> dict:
    kayitli = _ayarlari_oku(ayar_dosyasi or AYAR_DOSYASI).get(GENEL, {})
    sonuc = json.loads(json.dumps(VARSAYILAN_GENEL))
    sonuc["hiz"].update(kayitli.get("hiz", {}))
    sonuc["fiyatlar"].update(kayitli.get("fiyatlar", {}))
    if "canli_akis" in kayitli:
        sonuc["canli_akis"] = bool(kayitli["canli_akis"])
    return sonuc


def genel_ayarlari_kaydet(degerler: dict, ayar_dosyasi: Path | None = None) -> dict:
    yol = ayar_dosyasi or AYAR_DOSYASI
    with _kilit:
        ayar = _ayarlari_oku(yol)
        g = ayar.setdefault(GENEL, {})
        if "hiz" in degerler:
            g.setdefault("hiz", {}).update(
                {k: max(0, int(v or 0)) for k, v in degerler["hiz"].items() if k in SAGLAYICILAR})
        if "fiyatlar" in degerler:
            f = g.setdefault("fiyatlar", {})
            for model, deger in degerler["fiyatlar"].items():
                if deger is None:
                    f.pop(model, None)
                else:
                    f[model] = [max(0.0, float(deger[0])), max(0.0, float(deger[1]))]
        if "canli_akis" in degerler:
            g["canli_akis"] = bool(degerler["canli_akis"])
        _yaz(ayar, yol)
    return genel_ayarlar(yol)


def fiyat(model: str, genel: dict | None = None) -> list[float] | None:
    """Milyon token başına [giriş, çıkış] USD; yerel modeller ücretsiz; bilinmiyorsa None."""
    if saglayici(model) == "yerel":
        return [0.0, 0.0]
    genel = genel or genel_ayarlar()
    return genel["fiyatlar"].get(model) or VARSAYILAN_FIYATLAR.get(model)


def maliyet(model: str, giris: int, cikis: int, genel: dict | None = None) -> float | None:
    f = fiyat(model, genel)
    if f is None:
        return None
    return round((giris * f[0] + cikis * f[1]) / 1_000_000, 6)


# ------------------------------------------------------------- departman şablonları
def _calisan(isim, role, goal, backstory, tools=("file_read", "file_write")):
    return {"isim": isim, "role": role, "goal": goal, "backstory": backstory, "tools": list(tools)}


DEPARTMAN_SABLONLARI = {
    "web_ajansi": {
        "ad": "Web Ajansı",
        "aciklama": "Tasarım, ön yüz geliştirme ve SEO",
        "calisanlar": [
            _calisan("Defne", "UI/UX Tasarımcısı",
                     "Kullanıcı dostu, estetik ve erişilebilir arayüz tasarımları ve tasarım kararları üretmek.",
                     "Renk, tipografi ve yerleşim konusunda deneyimli bir tasarımcısın; kararlarını gerekçelendirirsin."),
            _calisan("Kerem", "Ön Yüz Geliştirici",
                     "Tasarımları temiz, duyarlı (responsive) HTML/CSS/JavaScript koduna dönüştürmek.",
                     "Standartlara uygun, hızlı ve erişilebilir web sayfaları yazan bir geliştiricisin.",
                     ("file_read", "file_write", "list_files")),
            _calisan("Sena", "SEO Uzmanı",
                     "Sayfaların arama motorlarında görünürlüğünü artıracak içerik ve teknik öneriler sunmak.",
                     "Anahtar kelime, meta etiketler ve site yapısı konusunda uzman bir SEO danışmanısın.",
                     ("file_read", "file_write", "web_ara", "web_oku")),
        ],
    },
    "pazarlama": {
        "ad": "Pazarlama Departmanı",
        "aciklama": "Strateji, sosyal medya ve reklam metinleri",
        "calisanlar": [
            _calisan("Ozan", "Pazarlama Stratejisti",
                     "Hedef kitleyi, konumlandırmayı ve kanal stratejisini belirleyen pazarlama planları hazırlamak.",
                     "Veriye dayalı düşünen, ölçülebilir hedefler koyan bir stratejistsin.",
                     ("file_read", "file_write", "web_ara", "web_oku")),
            _calisan("İpek", "Sosyal Medya Uzmanı",
                     "Platformlara uygun, etkileşim getiren sosyal medya içerikleri ve takvimleri hazırlamak.",
                     "Trendleri yakından takip eden, markanın sesini koruyan bir içerik üreticisisin."),
            _calisan("Emre", "Reklam Metin Yazarı",
                     "Dönüşüm odaklı, akılda kalıcı reklam metinleri ve sloganlar yazmak.",
                     "Kısa ve vurucu cümleler kuran, farklı tonlarda alternatifler sunan bir metin yazarısın."),
        ],
    },
    "hukuk": {
        "ad": "Hukuk Departmanı",
        "aciklama": "Sözleşme ve uyumluluk incelemesi",
        "calisanlar": [
            _calisan("Leyla", "Hukuk Danışmanı",
                     "Talepleri hukuki riskler ve mevzuat uyumu açısından değerlendirmek.",
                     "Dikkatli ve temkinli bir hukukçusun; kesin hukuki görüş yerine riskleri ve dikkat edilmesi "
                     "gerekenleri belirtir, gerektiğinde avukata danışılmasını önerirsin."),
            _calisan("Tarık", "Sözleşme Uzmanı",
                     "Açık, dengeli ve eksiksiz sözleşme taslakları ve maddeleri hazırlamak.",
                     "Sözleşme maddelerini sade bir dille yazan, belirsizlik bırakmayan bir uzmansın."),
        ],
    },
    "muhasebe": {
        "ad": "Muhasebe ve Finans",
        "aciklama": "Bütçe, maliyet ve finansal analiz",
        "calisanlar": [
            _calisan("Nil", "Mali Analist",
                     "Bütçe, maliyet ve kârlılık analizleri yapmak; finansal senaryolar hazırlamak.",
                     "Rakamlarla düşünen, varsayımlarını açıkça yazan bir analistsin."),
            _calisan("Hakan", "Muhasebeci",
                     "Gelir-gider tabloları, fatura ve vergi konularında düzenli ve doğru kayıtlar hazırlamak.",
                     "Titiz bir muhasebecisin; kesin vergi tavsiyesi yerine genel bilgi verir, "
                     "gerektiğinde mali müşavire danışılmasını önerirsin."),
        ],
    },
}


def sablon_uygula(sablon_id: str, ayar_dosyasi: Path = AYAR_DOSYASI) -> str:
    sablon = DEPARTMAN_SABLONLARI.get(sablon_id)
    if not sablon:
        raise KeyError(sablon_id)
    dkey = departman_ekle(sablon["ad"], ayar_dosyasi)
    for c in sablon["calisanlar"]:
        masa_ekle(dkey, c, ayar_dosyasi)
    return dkey
