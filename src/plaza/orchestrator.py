"""CEO merkezli iş akışı.

1. Talep her zaman önce CEO'ya gelir. CEO talebi inceler ve bir iş planı çıkarır:
   hangi çalışan, hangi sırayla, hangi görevi yapacak.
2. Görevler sırayla departmanlara gider. Her çalışan kendisinden önceki
   çalışanların çıktılarını görür, değerlendirir ve kendi katkısını ekler.
3. CEO sonuçları değerlendirir; yetersiz bulursa ilgili çalışanlara revizyon
   gönderir (en fazla `max_revizyon` tur), sonra nihai teslimat raporunu yazar.

Her adım `emit(tip, **veri)` ile arayüze olay olarak bildirilir.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .office import make_llm
from .settings import Desk, Office
from .tools import build_tools

Emit = Callable[..., None]
MAX_BAGLAM = 6000


class Durduruldu(Exception):
    """Kullanıcı işi durdurdu."""


@dataclass
class Adim:
    calisan: str
    gorev: str


def _json_ayikla(metin: str) -> dict:
    m = re.search(r"\{.*\}", metin, re.S)
    if not m:
        raise ValueError("Yanıtta JSON bulunamadı")
    return json.loads(m.group(0))


def _kisalt(s: str, n: int = MAX_BAGLAM) -> str:
    return s if len(s) <= n else s[:n] + "\n…(kısaltıldı)"


class IsAkisi:
    def __init__(
        self,
        office: Office,
        talep: str,
        emit: Emit,
        workdir: Path,
        simulasyon: bool = False,
        max_revizyon: int = 1,
        iptal: threading.Event | None = None,
    ):
        self.office = office
        self.talep = talep
        self.emit = emit
        self.workdir = workdir
        self.simulasyon = simulasyon
        self.max_revizyon = max_revizyon
        self.iptal = iptal or threading.Event()
        self.plan_ozeti = ""
        self.ciktilar: dict[str, str] = {}  # çalışan -> en güncel çıktı (sıra korunur)

    # ------------------------------------------------------------------ akış
    def calistir(self) -> str:
        ceo = self.office.ceo
        self.emit("durum", masa="ceo", durum="dusunuyor", aciklama="Talebi inceliyor, plan çıkarıyor")
        self.plan_ozeti, adimlar = self._planla()
        self.emit("plan", ozet=self.plan_ozeti, adimlar=[a.__dict__ for a in adimlar])
        self.emit("durum", masa="ceo", durum="bekliyor", aciklama="Departmanları bekliyor")

        self._adimlari_calistir(adimlar, tur=0)

        tur = 0
        while True:
            self._kontrol()
            son_tur = tur >= self.max_revizyon
            self.emit("durum", masa="ceo", durum="dusunuyor", aciklama="Sonuçları değerlendiriyor")
            onay, revizyonlar = self._degerlendir(son_tur)
            if onay or son_tur or not revizyonlar:
                self.emit("degerlendirme", onay=True, tur=tur, revizyonlar=[])
                break
            tur += 1
            self.emit("degerlendirme", onay=False, tur=tur, revizyonlar=[a.__dict__ for a in revizyonlar])
            self.emit("durum", masa="ceo", durum="bekliyor", aciklama=f"Revizyon turu {tur}")
            self._adimlari_calistir(revizyonlar, tur=tur)

        self._kontrol()
        self.emit("durum", masa="ceo", durum="calisiyor", aciklama="Nihai raporu yazıyor")
        sonuc = self._rapor()
        self.emit("durum", masa="ceo", durum="bitti", aciklama=f"{ceo.isim} işi teslim etti")
        return sonuc

    def _kontrol(self) -> None:
        if self.iptal.is_set():
            raise Durduruldu()

    def _adimlari_calistir(self, adimlar: list[Adim], tur: int) -> None:
        for a in adimlar:
            self._kontrol()
            desk = self.office.desk(a.calisan)
            self.emit("gorev_atandi", kimden="ceo", kime=desk.key, gorev=a.gorev, tur=tur)
            self.emit("durum", masa=desk.key, durum="calisiyor", aciklama=a.gorev[:120])
            try:
                cikti = self._calisan(desk, a.gorev, tur)
            except Exception:
                self.emit("durum", masa=desk.key, durum="hata", aciklama="Görev başarısız")
                raise
            self.ciktilar.pop(desk.key, None)
            self.ciktilar[desk.key] = cikti
            self.emit("gorev_bitti", kime=desk.key, cikti=cikti, tur=tur)
            self.emit("durum", masa=desk.key, durum="bitti", aciklama="Görevi CEO'ya teslim etti")

    # --------------------------------------------------------------- CEO
    def _ceo_sistem(self) -> str:
        c = self.office.ceo
        return (
            f"Sen Plaza'nın {c.role}'susun, adın {c.isim}. {c.goal}\n{c.backstory}\n"
            "Plaza'ya gelen tüm talepler önce sana gelir. İşi kendin yapmazsın; departmanlara dağıtır, "
            "sonucu denetlersin. Her zaman Türkçe yanıt verirsin."
        )

    def _ekip_metni(self) -> str:
        return "\n".join(
            f"- {s.key}: {s.isim}, {s.role} ({s.department}) — {s.goal}" for s in self.office.aktif_calisanlar()
        )

    def _ceo_cagir(self, kullanici: str) -> str:
        llm = make_llm(self.office.ceo.model)
        return str(llm.call([
            {"role": "system", "content": self._ceo_sistem()},
            {"role": "user", "content": kullanici},
        ]))

    def _adimlari_dogrula(self, ham: list) -> list[Adim]:
        aktif = {s.key for s in self.office.aktif_calisanlar()}
        return [
            Adim(calisan=str(a["calisan"]), gorev=str(a["gorev"]).strip())
            for a in ham or []
            if isinstance(a, dict) and a.get("calisan") in aktif and str(a.get("gorev", "")).strip()
        ]

    def _planla(self) -> tuple[str, list[Adim]]:
        aktifler = self.office.aktif_calisanlar()
        if not aktifler:
            raise ValueError("Ofiste aktif çalışan yok. En az bir masayı aktif yapın.")
        if self.simulasyon:
            time.sleep(1.5)
            return (
                "Simülasyon: talep tüm aktif departmanlardan sırayla geçecek.",
                [Adim(s.key, f"{s.role} olarak talebe kendi uzmanlık alanından katkı ver.") for s in aktifler],
            )
        yanit = self._ceo_cagir(
            f"Yeni talep:\n\n{self.talep}\n\nEkibin (anahtar: kişi, rol, departman — hedef):\n{self._ekip_metni()}\n\n"
            "Talebi analiz et ve bir iş planı çıkar. Her adım tek bir çalışana verilen net bir talimattır. "
            "Çalışanlar adımları sırayla yapar ve önceki adımların çıktılarını görerek değerlendirir. "
            "Yalnızca gerekli çalışanları dahil et; bir çalışan birden fazla adımda yer alabilir.\n\n"
            'Yalnızca şu biçimde JSON döndür:\n{"ozet": "planın kısa özeti", '
            '"adimlar": [{"calisan": "<anahtar>", "gorev": "çalışana talimat"}]}'
        )
        try:
            veri = _json_ayikla(yanit)
            adimlar = self._adimlari_dogrula(veri.get("adimlar"))
            ozet = str(veri.get("ozet", "")).strip()
        except (ValueError, json.JSONDecodeError):
            adimlar, ozet = [], ""
        if not adimlar:
            ozet = ozet or "Plan okunamadı; talep tüm aktif departmanlardan sırayla geçecek."
            adimlar = [Adim(s.key, f"Talebe {s.role} olarak katkı ver.") for s in aktifler]
        return ozet, adimlar

    def _ciktilar_metni(self) -> str:
        parcalar = []
        for key, cikti in self.ciktilar.items():
            d = self.office.desk(key)
            parcalar.append(f"### {d.isim} — {d.role} ({d.department})\n{_kisalt(cikti)}")
        return "\n\n".join(parcalar) or "(henüz çıktı yok)"

    def _degerlendir(self, son_tur: bool) -> tuple[bool, list[Adim]]:
        if self.simulasyon:
            time.sleep(1.5)
            if son_tur or not self.ciktilar:
                return True, []
            key = random.choice(list(self.ciktilar))
            return False, [Adim(key, "Çıktını daha somut örneklerle güçlendir.")]
        if son_tur:
            return True, []
        yanit = self._ceo_cagir(
            f"Talep:\n{self.talep}\n\nPlanın: {self.plan_ozeti}\n\nDepartmanlardan gelen çıktılar:\n\n"
            f"{self._ciktilar_metni()}\n\nEkip:\n{self._ekip_metni()}\n\n"
            "Bu çıktılar talebi tam ve kaliteli karşılıyor mu? Karşılıyorsa onay ver. Karşılamıyorsa "
            "yalnızca gerçekten düzeltilmesi gerekenler için ilgili çalışanlara net revizyon talimatı yaz.\n\n"
            'Yalnızca şu biçimde JSON döndür:\n{"onay": true|false, '
            '"revizyonlar": [{"calisan": "<anahtar>", "gorev": "ne düzeltilmeli"}]}'
        )
        try:
            veri = _json_ayikla(yanit)
        except (ValueError, json.JSONDecodeError):
            return True, []
        return bool(veri.get("onay")), self._adimlari_dogrula(veri.get("revizyonlar"))

    def _rapor(self) -> str:
        if self.simulasyon:
            time.sleep(1.5)
            satirlar = "\n".join(
                f"- **{self.office.desk(k).isim}** ({self.office.desk(k).role}): görevini tamamladı."
                for k in self.ciktilar
            )
            return (
                f"# Nihai Teslimat (simülasyon)\n\n**Talep:** {self.talep}\n\n## Kim ne yaptı\n{satirlar}\n\n"
                "## Not\nBu bir simülasyon çıktısıdır; Claude çağrılmadı."
            )
        return self._ceo_cagir(
            f"Talep:\n{self.talep}\n\nDepartmanlardan gelen nihai çıktılar:\n\n{self._ciktilar_metni()}\n\n"
            "Talep sahibine sunulacak nihai teslimatı Markdown olarak yaz: sonucun kendisi (talep bir "
            "metin/rapor/plan ise eksiksiz hali), hangi çalışanın ne yaptığı, üretilen dosyalar ve açık kalan "
            "konular. JSON kullanma."
        )

    # ------------------------------------------------------------ çalışan
    def _calisan(self, desk: Desk, gorev: str, tur: int) -> str:
        if self.simulasyon:
            time.sleep(random.uniform(2.0, 4.0))
            ek = " (revize edildi)" if tur else ""
            return (
                f"## {desk.role} çıktısı{ek}\n\n- Talep incelendi: _{self.talep[:80]}_\n"
                f"- Önceki {len(self.ciktilar)} çıktı değerlendirildi.\n- {gorev}\n\nSimülasyon çıktısıdır."
            )

        from crewai import Agent, Crew, Process, Task

        onceki = {k: v for k, v in self.ciktilar.items() if k != desk.key}
        baglam = ""
        if onceki:
            baglam = "\n\nEkip arkadaşlarının şimdiye kadarki çıktıları (değerlendir ve üzerine inşa et):\n\n" + "\n\n".join(
                f"### {self.office.desk(k).isim} — {self.office.desk(k).role}\n{_kisalt(v)}" for k, v in onceki.items()
            )
        if tur and desk.key in self.ciktilar:
            baglam += f"\n\nBu bir REVİZYON. Önceki çıktın:\n{_kisalt(self.ciktilar[desk.key])}"

        agent = Agent(
            role=desk.role,
            goal=desk.goal,
            backstory=f"Adın {desk.isim}. {desk.backstory}\n{desk.department} çalışanısın. Her zaman Türkçe yanıt verirsin.",
            tools=build_tools(desk.tools, self.workdir),
            llm=make_llm(desk.model),
            allow_delegation=False,
            verbose=False,
        )
        task = Task(
            description=(
                f"Plaza'ya gelen talep (CEO üzerinden):\n\n{self.talep}\n\n"
                f"CEO'nun sana verdiği görev:\n{gorev}{baglam}\n\n"
                "Dosya üretmen gerekiyorsa araçlarınla çalışma klasörüne yaz."
            ),
            expected_output="Görevin eksiksiz, Türkçe çıktısı.",
            agent=agent,
        )
        sonuc = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False).kickoff()
        return str(sonuc.raw)
