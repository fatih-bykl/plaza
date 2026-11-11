"""Ofis yapılandırması: departments.yaml + masa bazlı kullanıcı ayarları (ofis.json).

Arayüzden bir masaya tıklayıp yapılan değişiklikler (model, rol, hedef, araçlar…)
ofis.json dosyasına yazılır; YAML dosyası olduğu gibi kalır.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .office import DEFAULT_MODEL, load_org
from .tools import TOOL_TYPES

AYAR_DOSYASI = Path(os.getenv("PLAZA_OFIS_AYAR", "ofis.json"))
DUZENLENEBILIR = {"isim", "model", "role", "goal", "backstory", "tools", "aktif"}

# Sağlayıcılar: model kimliğinin öneki → gereken ortam değişkeni(leri)
SAGLAYICILAR = {
    "anthropic": {"ad": "Anthropic (Claude)", "anahtarlar": ["ANTHROPIC_API_KEY"]},
    "google": {"ad": "Google (Gemini)", "anahtarlar": ["GOOGLE_API_KEY", "GEMINI_API_KEY"]},
    "deepseek": {"ad": "DeepSeek", "anahtarlar": ["DEEPSEEK_API_KEY"]},
}
_ONEK = {"anthropic": "anthropic", "claude": "anthropic", "gemini": "google", "google": "google", "deepseek": "deepseek"}

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
]


def saglayici(model: str) -> str | None:
    """'gemini/gemini-4-argon' → 'google'. Bilinmeyen önek için None."""
    onek = model.split("/", 1)[0].lower() if "/" in model else ("anthropic" if model.startswith("claude-") else "")
    return _ONEK.get(onek)


def anahtar_var(saglayici_adi: str) -> bool:
    return any(os.getenv(k, "").strip() for k in SAGLAYICILAR[saglayici_adi]["anahtarlar"])


def anahtar_durumu() -> dict[str, bool]:
    return {s: anahtar_var(s) for s in SAGLAYICILAR}


def eksik_anahtarlar(office: "Office") -> list[str]:
    """Aktif masaların (ve CEO'nun) modelleri için tanımlı olmayan API anahtarları."""
    eksik = []
    for d in [office.ceo, *office.aktif_calisanlar()]:
        s = saglayici(d.model)
        if s and not anahtar_var(s):
            mesaj = f"{d.isim} ({SAGLAYICILAR[s]['ad']}): {' veya '.join(SAGLAYICILAR[s]['anahtarlar'])}"
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
