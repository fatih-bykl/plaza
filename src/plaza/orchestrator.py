"""CEO merkezli iş akışı.

1. Talep her zaman önce CEO'ya gelir. CEO talebi inceler ve aşamalı bir iş planı
   çıkarır: hangi çalışan, hangi aşamada, hangi görevi yapacak. İstenirse plan
   kullanıcı onayına sunulur ve kullanıcı planı düzenleyebilir.
2. Aşamalar sırayla yürür; aynı aşamadaki görevler PARALEL çalışır. Her çalışan
   önceki aşamaların çıktılarını görür, değerlendirir ve kendi katkısını ekler.
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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .hatalar import Durduruldu, bekleme_aciklamasi, gecici_mi, onerilen_bekleme
from .llm import CanliTampon, akis_ayir, akis_baglan, kullanim, llm_olustur
from .settings import Desk, Office, arac_destekli, genel_ayarlar, maliyet
from .tools import build_tools

Emit = Callable[..., None]
MAX_BAGLAM = 6000
MAX_EK = 4000
BEKLEMELER = (5, 15, 30)  # geçici hatalarda yeniden deneme aralıkları (sn)



@dataclass
class Adim:
    calisan: str
    gorev: str
    asama: int = 1


def _json_ayikla(metin: str) -> dict:
    m = re.search(r"\{.*\}", metin, re.S)
    if not m:
        raise ValueError("Yanıtta JSON bulunamadı")
    return json.loads(m.group(0))


def _temizle(metin: str) -> str:
    """Düşünen modellerin (ör. DeepSeek R1) <think>…</think> bölümlerini çıkarır."""
    metin = re.sub(r"<think>.*?</think>", "", metin, flags=re.S)
    metin = re.sub(r"^.*?</think>", "", metin, flags=re.S).strip()
    # Tüm yanıtı tek bir ```markdown bloğuna saran modeller için dış çiti kaldır
    m = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", metin, flags=re.S)
    return m.group(1).strip() if m else metin


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
        plan_onayi: bool = False,
        onceki_sonuc: str = "",
        ekler: list[tuple[str, str]] | None = None,
        devam: dict | None = None,
        canli: Callable[[str, str], None] | None = None,
    ):
        self.office = office
        self.talep = talep
        self.emit = emit
        self.workdir = workdir
        self.simulasyon = simulasyon
        self.max_revizyon = max_revizyon
        self.iptal = iptal or threading.Event()
        self.plan_onayi = plan_onayi
        self.onceki_sonuc = onceki_sonuc
        self.ekler = ekler or []
        self.plan_ozeti = ""
        self.ciktilar: dict[str, str] = {}  # çalışan -> en güncel çıktı (sıra korunur)
        self._kilit = threading.Lock()
        self._onay = threading.Event()
        self._onaylanan: list[Adim] = []
        self._ceo_llm = None
        self._ceo_model = office.ceo.model
        self._ceo_llmler: list[tuple[str, object]] = []  # (model, llm) — kullanım/maliyet için
        self.istatistik: dict[str, dict] = {}  # çalışan -> {gorev, sure, token, maliyet}
        self.genel = genel_ayarlar()
        self.devam = devam  # yarıda kalmış bir işin kaydı: kaldığı yerden devam
        self.canli = canli  # canli(masa, metin_parcasi): kaydedilmeyen canlı akış
        self.plan: list[Adim] = []
        self.tamamlanan: list[list] = []  # [calisan, gorev, asama] — ilk turda biten adımlar

    # ------------------------------------------------------------------ akış
    def calistir(self) -> str:
        ceo = self.office.ceo
        if self.devam:
            # Kaldığı yerden: plan ve biten adımların çıktıları önceki denemeden gelir
            self.plan_ozeti = self.devam.get("plan_ozeti", "")
            adimlar = self._adimlari_dogrula(self.devam.get("adimlar"))
            aktif = {s.key for s in self.office.aktif_calisanlar()}
            self.ciktilar = {k: v for k, v in (self.devam.get("ciktilar") or {}).items() if k in aktif}
            self.tamamlanan = [t for t in self.devam.get("tamamlanan", []) if t[0] in self.ciktilar]
            if not adimlar:
                raise ValueError("Önceki işin planı okunamadı; işi yeniden başlatın.")
            self.emit("plan", ozet=self.plan_ozeti, adimlar=[asdict(a) for a in adimlar],
                      tamamlanan=self.tamamlanan, devam=True)
        else:
            self.emit("durum", masa="ceo", durum="dusunuyor", aciklama="Talebi inceliyor, plan çıkarıyor")
            self.plan_ozeti, adimlar = self._planla()
            if self.plan_onayi:
                adimlar = self._onay_bekle(adimlar)
            self.emit("plan", ozet=self.plan_ozeti, adimlar=[asdict(a) for a in adimlar])
        self.plan = adimlar
        self.emit("durum", masa="ceo", durum="bekliyor", aciklama="Departmanları bekliyor")

        biten = {(t[0], t[1], t[2]) for t in self.tamamlanan}
        self._asamalari_calistir([a for a in adimlar if (a.calisan, a.gorev, a.asama) not in biten], tur=0)

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
            for r in revizyonlar:
                r.asama = 1  # revizyonlar birlikte (paralel) yapılır
            self.emit("degerlendirme", onay=False, tur=tur, revizyonlar=[asdict(a) for a in revizyonlar])
            self.emit("durum", masa="ceo", durum="bekliyor", aciklama=f"Revizyon turu {tur}")
            self._asamalari_calistir(revizyonlar, tur=tur)

        self._kontrol()
        self.emit("durum", masa="ceo", durum="calisiyor", aciklama="Nihai raporu yazıyor")
        sonuc = self._rapor()
        self.emit("durum", masa="ceo", durum="bitti", aciklama=f"{ceo.isim} işi teslim etti")
        return sonuc

    def ozet_istatistik(self) -> dict:
        ceo_token, ceo_maliyet, eksik = 0, 0.0, False
        for model, llm in self._ceo_llmler:
            g, c = kullanim(llm)
            ceo_token += g + c
            m = maliyet(model, g, c, self.genel)
            if m is None:
                eksik = eksik or (g + c) > 0
            else:
                ceo_maliyet += m
        calisan_token = sum(v["token"] for v in self.istatistik.values())
        calisan_maliyet = 0.0
        for v in self.istatistik.values():
            if v.get("maliyet") is None:
                eksik = eksik or v["token"] > 0
            else:
                calisan_maliyet += v["maliyet"]
        return {
            "ceo_token": ceo_token, "toplam_token": ceo_token + calisan_token, "calisanlar": self.istatistik,
            "ceo_maliyet": round(ceo_maliyet, 6), "toplam_maliyet": round(ceo_maliyet + calisan_maliyet, 6),
            "maliyet_eksik": eksik,
        }

    def kayit(self) -> dict:
        """Yarıda kalırsa kaldığı yerden devam edebilmek için gereken durum."""
        return {
            "plan_ozeti": self.plan_ozeti,
            "adimlar": [asdict(a) for a in self.plan],
            "ciktilar": dict(self.ciktilar),
            "tamamlanan": list(self.tamamlanan),
        }

    def _bekleme_bildirimi(self, masa: str, durum: str):
        def bildir(saniye: float) -> None:
            if saniye > 0:
                self.emit("durum", masa=masa, durum="bekliyor",
                          aciklama=f"İstek hızı sınırı: {saniye:.0f} sn bekleniyor")
            else:
                self.emit("durum", masa=masa, durum=durum, aciklama="Devam ediyor")
        return bildir

    def _kontrol(self) -> None:
        if self.iptal.is_set():
            raise Durduruldu()

    # ------------------------------------------------------------ plan onayı
    def _onay_bekle(self, adimlar: list[Adim]) -> list[Adim]:
        self.emit("plan_onay_bekleniyor", ozet=self.plan_ozeti, adimlar=[asdict(a) for a in adimlar])
        self.emit("durum", masa="ceo", durum="bekliyor", aciklama="Planın onayınızı bekliyor")
        while not self._onay.wait(0.5):
            self._kontrol()
        return self._onaylanan

    def plani_onayla(self, ham: list) -> None:
        """Kullanıcının (düzenlenmiş) planını kabul eder. Arayüzden çağrılır."""
        adimlar = self._adimlari_dogrula(ham)
        if not adimlar:
            raise ValueError("Plan en az bir geçerli adım içermeli.")
        self._onaylanan = adimlar
        self._onay.set()

    @property
    def onay_bekliyor(self) -> bool:
        return self.plan_onayi and not self._onay.is_set()

    # -------------------------------------------------------------- yürütme
    def _asamalari_calistir(self, adimlar: list[Adim], tur: int) -> None:
        for asama in sorted({a.asama for a in adimlar}):
            kalan = [a for a in adimlar if a.asama == asama]
            while kalan:  # aynı çalışan bir aşamada iki kez varsa sıraya koy
                parti, sonraki, gorulen = [], [], set()
                for a in kalan:
                    (sonraki if a.calisan in gorulen else parti).append(a)
                    gorulen.add(a.calisan)
                self._kontrol()
                self._parti_calistir(parti, tur)
                kalan = sonraki

    def _parti_calistir(self, parti: list[Adim], tur: int) -> None:
        with self._kilit:
            onceki = dict(self.ciktilar)  # aşama içindekiler birbirini görmez
        for a in parti:
            self.emit("gorev_atandi", kimden="ceo", kime=a.calisan, gorev=a.gorev, tur=tur, asama=a.asama)
            self.emit("durum", masa=a.calisan, durum="calisiyor", aciklama=a.gorev[:120])
        if len(parti) == 1:
            self._tek_adim(parti[0], tur, onceki)
            return
        with ThreadPoolExecutor(max_workers=len(parti)) as havuz:
            isler = [havuz.submit(self._tek_adim, a, tur, onceki) for a in parti]
            hatalar = [f.exception() for f in isler if f.exception()]
        if hatalar:
            raise hatalar[0]

    def _tek_adim(self, a: Adim, tur: int, onceki: dict[str, str]) -> None:
        desk = self.office.desk(a.calisan)
        bas = time.monotonic()
        model = desk.model
        try:
            try:
                cikti, giris, cikis = self._yeniden_dene(
                    desk.key, "calisiyor", lambda: self._calisan(desk, a.gorev, tur, onceki, model))
            except Durduruldu:
                raise
            except Exception:
                if not desk.yedek_model or desk.yedek_model == model or self.simulasyon:
                    raise
                model = desk.yedek_model
                self.emit("durum", masa=desk.key, durum="calisiyor",
                          aciklama=f"Ana model yanıt vermedi; yedek modele geçildi ({model})")
                cikti, giris, cikis = self._yeniden_dene(
                    desk.key, "calisiyor", lambda: self._calisan(desk, a.gorev, tur, onceki, model))
        except Durduruldu:
            raise
        except Exception as e:
            self.emit("durum", masa=desk.key, durum="hata", aciklama="Görev başarısız")
            e.plaza_masa = f"{desk.isim} ({desk.role})"  # hata mesajında hangi masa olduğu görünsün
            raise
        sure = round(time.monotonic() - bas, 1)
        token = giris + cikis
        tutar = maliyet(model, giris, cikis, self.genel)
        with self._kilit:
            self.ciktilar.pop(desk.key, None)
            self.ciktilar[desk.key] = cikti
            if tur == 0:
                self.tamamlanan.append([a.calisan, a.gorev, a.asama])
            s = self.istatistik.setdefault(desk.key, {"gorev": 0, "sure": 0.0, "token": 0, "maliyet": 0.0})
            s["gorev"] += 1
            s["sure"] = round(s["sure"] + sure, 1)
            s["token"] += token
            s["maliyet"] = None if (tutar is None or s["maliyet"] is None) else round(s["maliyet"] + tutar, 6)
        self.emit("gorev_bitti", kime=desk.key, cikti=cikti, tur=tur, asama=a.asama, sure=sure, token=token,
                  giris=giris, cikis=cikis, maliyet=tutar, model=model)
        self.emit("durum", masa=desk.key, durum="bitti", aciklama="Görevi CEO'ya teslim etti")

    # --------------------------------------------------------------- bağlam
    def _ek_baglam(self) -> str:
        parcalar = []
        if self.onceki_sonuc:
            parcalar.append(
                "Bu iş, daha önce tamamlanmış bir işin DEVAMIDIR. Önceki işin nihai sonucu:\n"
                f"{_kisalt(self.onceki_sonuc)}\n(Önceki işin dosyaları çalışma klasöründe 'onceki/' altındadır.)"
            )
        for ad, icerik in self.ekler:
            parcalar.append(f"Talep sahibinin eklediği dosya 'girdi/{ad}':\n{_kisalt(icerik, MAX_EK)}")
        return ("\n\n" + "\n\n".join(parcalar)) if parcalar else ""

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

    def _ceo_modeli_kur(self, model: str) -> None:
        self._ceo_model = model
        self._ceo_llm = llm_olustur(model, iptal=self.iptal,
                                    bekleme_bildir=self._bekleme_bildirimi("ceo", "dusunuyor"))
        self._ceo_llmler.append((model, self._ceo_llm))

    def _ceo_cagir(self, kullanici: str, durum: str = "dusunuyor") -> str:
        if self._ceo_llm is None:
            self._ceo_modeli_kur(self.office.ceo.model)
        mesajlar = [
            {"role": "system", "content": self._ceo_sistem()},
            {"role": "user", "content": kullanici},
        ]
        try:
            try:
                yanit = self._yeniden_dene("ceo", durum, lambda: self._ceo_llm.call(mesajlar))
            except Durduruldu:
                raise
            except Exception:
                yedek = self.office.ceo.yedek_model
                if not yedek or yedek == self._ceo_model:
                    raise
                self._ceo_modeli_kur(yedek)
                self.emit("durum", masa="ceo", durum=durum,
                          aciklama=f"Ana model yanıt vermedi; yedek modele geçildi ({yedek})")
                yanit = self._yeniden_dene("ceo", durum, lambda: self._ceo_llm.call(mesajlar))
        except Durduruldu:
            raise
        except Exception as e:
            self.emit("durum", masa="ceo", durum="hata", aciklama="Yanıt alınamadı")
            e.plaza_masa = f"{self.office.ceo.isim} (CEO)"
            raise
        return _temizle(str(yanit))

    def _yeniden_dene(self, masa: str, durum: str, islem):
        """Geçici hatalarda (sunucu yoğun, dakikalık sınır, bağlantı) bekleyip yeniden dener."""
        for deneme in range(len(BEKLEMELER) + 1):
            try:
                return islem()
            except Durduruldu:
                raise
            except Exception as e:
                if deneme == len(BEKLEMELER) or not gecici_mi(e):
                    raise
                bekle = onerilen_bekleme(e, BEKLEMELER[deneme])
                self.emit("durum", masa=masa, durum="bekliyor",
                          aciklama=bekleme_aciklamasi(e, bekle, deneme + 1, len(BEKLEMELER)))
                if self.iptal.wait(bekle):
                    raise Durduruldu()
                self.emit("durum", masa=masa, durum=durum, aciklama="Tekrar deniyor")

    def _adimlari_dogrula(self, ham: list) -> list[Adim]:
        aktif = {s.key for s in self.office.aktif_calisanlar()}
        adimlar = []
        for a in ham or []:
            if not isinstance(a, dict) or a.get("calisan") not in aktif or not str(a.get("gorev", "")).strip():
                continue
            try:
                asama = max(1, int(a.get("asama", 1)))
            except (TypeError, ValueError):
                asama = 1
            adimlar.append(Adim(calisan=str(a["calisan"]), gorev=str(a["gorev"]).strip(), asama=asama))
        # aşamaları 1..n olarak sıkıştır, sıraya diz
        sira = {a: i + 1 for i, a in enumerate(sorted({x.asama for x in adimlar}))}
        for x in adimlar:
            x.asama = sira[x.asama]
        return sorted(adimlar, key=lambda x: x.asama)

    def _planla(self) -> tuple[str, list[Adim]]:
        aktifler = self.office.aktif_calisanlar()
        if not aktifler:
            raise ValueError("Ofiste aktif çalışan yok. En az bir masayı aktif yapın.")
        if self.simulasyon:
            time.sleep(1.5)
            deps = list(dict.fromkeys(s.department_key for s in aktifler))
            n = len(deps)

            def asama(dkey: str) -> int:
                i = deps.index(dkey)
                return 1 if i == 0 else (3 if i == n - 1 and n > 2 else 2)

            return (
                "Simülasyon: ilk departman hazırlık yapar, ortadakiler paralel çalışır, son departman toparlar.",
                [Adim(s.key, f"{s.role} olarak talebe kendi uzmanlık alanından katkı ver.", asama(s.department_key))
                 for s in aktifler],
            )
        yanit = self._ceo_cagir(
            f"Yeni talep:\n\n{self.talep}{self._ek_baglam()}\n\n"
            f"Ekibin (anahtar: kişi, rol, departman — hedef):\n{self._ekip_metni()}\n\n"
            "Talebi analiz et ve aşamalı bir iş planı çıkar. Her adım tek bir çalışana verilen net bir talimattır. "
            "Aşamalar sırayla yürür; AYNI aşamadaki adımlar paralel çalışır ve yalnızca önceki aşamaların "
            "çıktılarını görür. Birbirinin çıktısına ihtiyaç duymayan işleri aynı aşamaya koyarak işi hızlandır; "
            "bağımlı işleri sonraki aşamalara koy.\n"
            "ÖNEMLİ: Yalnızca gerçekten gerekli çalışanları dahil et; her ek çalışan zaman ve maliyet demektir. "
            "Basit bir talep (ör. kısa bir metin, tek bir sayfa, küçük bir kod) için 1-2 çalışan yeterlidir; "
            "tüm ekibi yalnızca büyük ve çok yönlü işlerde kullan.\n\n"
            'Yalnızca şu biçimde JSON döndür:\n{"ozet": "planın kısa özeti", '
            '"adimlar": [{"asama": 1, "calisan": "<anahtar>", "gorev": "çalışana talimat"}]}'
        )
        try:
            veri = _json_ayikla(yanit)
            adimlar = self._adimlari_dogrula(veri.get("adimlar"))
            ozet = str(veri.get("ozet", "")).strip()
        except (ValueError, json.JSONDecodeError):
            adimlar, ozet = [], ""
        if not adimlar:
            ozet = ozet or "Plan okunamadı; talep tüm aktif departmanlardan sırayla geçecek."
            adimlar = [Adim(s.key, f"Talebe {s.role} olarak katkı ver.", i + 1) for i, s in enumerate(aktifler)]
        return ozet, adimlar

    def _ciktilar_metni(self, ciktilar: dict[str, str] | None = None) -> str:
        parcalar = []
        for key, cikti in (self.ciktilar if ciktilar is None else ciktilar).items():
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
            f"Talep:\n{self.talep}{self._ek_baglam()}\n\nPlanın: {self.plan_ozeti}\n\n"
            f"Departmanlardan gelen çıktılar:\n\n{self._ciktilar_metni()}\n\nEkip:\n{self._ekip_metni()}\n\n"
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
            ek = f"\n\n**Ek dosyalar:** {', '.join(a for a, _ in self.ekler)}" if self.ekler else ""
            devam = "\n\n_Bu iş önceki bir işin devamıdır._" if self.onceki_sonuc else ""
            return (
                f"# Nihai Teslimat (simülasyon)\n\n**Talep:** {self.talep}{ek}{devam}\n\n## Kim ne yaptı\n{satirlar}\n\n"
                "## Not\nBu bir simülasyon çıktısıdır; yapay zekâ çağrılmadı."
            )
        return self._ceo_cagir(durum="calisiyor", kullanici=
            f"Talep:\n{self.talep}{self._ek_baglam()}\n\nDepartmanlardan gelen nihai çıktılar:\n\n"
            f"{self._ciktilar_metni()}\n\n"
            "Talep sahibine sunulacak nihai teslimatı Markdown olarak yaz: sonucun kendisi (talep bir "
            "metin/rapor/plan ise eksiksiz hali), hangi çalışanın ne yaptığı, üretilen dosyalar ve açık kalan "
            "konular. JSON kullanma."
        )

    # ------------------------------------------------------------ çalışan
    def _calisan(self, desk: Desk, gorev: str, tur: int, onceki: dict[str, str],
                 model: str | None = None) -> tuple[str, int, int]:
        """Bir çalışanın görevini yürütür; (çıktı, giriş token, çıkış token) döndürür."""
        model = model or desk.model
        if self.simulasyon:
            time.sleep(random.uniform(2.0, 4.0))
            if self.iptal.is_set():
                raise Durduruldu()
            ek = " (revize edildi)" if tur else ""
            return (
                f"## {desk.role} çıktısı{ek}\n\n- Talep incelendi: _{self.talep[:80]}_\n"
                f"- Önceki {len(onceki)} çıktı değerlendirildi.\n- {gorev}\n\nSimülasyon çıktısıdır.",
                0, 0,
            )

        from crewai import Agent, Crew, Process, Task

        digerleri = {k: v for k, v in onceki.items() if k != desk.key}
        baglam = ""
        if digerleri:
            baglam = "\n\nEkip arkadaşlarının şimdiye kadarki çıktıları (değerlendir ve üzerine inşa et):\n\n" + \
                self._ciktilar_metni(digerleri)
        if tur and desk.key in onceki:
            baglam += f"\n\nBu bir REVİZYON. Önceki çıktın:\n{_kisalt(onceki[desk.key])}"

        akis = bool(self.genel.get("canli_akis")) and self.canli is not None
        llm = llm_olustur(model, stream=akis, iptal=self.iptal,
                          bekleme_bildir=self._bekleme_bildirimi(desk.key, "calisiyor"))
        araclar = build_tools(desk.tools, self.workdir) if arac_destekli(model) else []
        if desk.tools and not araclar:
            baglam += ("\n\nNot: Kullandığın yerel model dosya araçlarını desteklemiyor; dosya yazamazsın. "
                       "Üretmen gereken dosyaların içeriğini çıktında dosya adlarıyla birlikte ver.")
        agent = Agent(
            role=desk.role,
            goal=desk.goal,
            backstory=f"Adın {desk.isim}. {desk.backstory}\n{desk.department} çalışanısın. Her zaman Türkçe yanıt verirsin.",
            tools=araclar,
            llm=llm,
            allow_delegation=False,
            verbose=False,
        )
        task = Task(
            description=(
                f"Plaza'ya gelen talep (CEO üzerinden):\n\n{self.talep}{self._ek_baglam()}\n\n"
                f"CEO'nun sana verdiği görev:\n{gorev}{baglam}\n\n"
                "Dosya üretmen gerekiyorsa araçlarınla çalışma klasörüne yaz."
            ),
            expected_output="Görevin eksiksiz, Türkçe çıktısı.",
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        if akis:
            tampon = CanliTampon(lambda metin: self.canli(desk.key, metin))
            akis_baglan(str(agent.id), tampon)
            try:
                with tampon:
                    sonuc = crew.kickoff()
            finally:
                akis_ayir(str(agent.id))
        else:
            sonuc = crew.kickoff()
        u = sonuc.token_usage
        giris, cikis = int(getattr(u, "prompt_tokens", 0) or 0), int(getattr(u, "completion_tokens", 0) or 0)
        if not (giris or cikis):
            giris, cikis = kullanim(llm)
        return _temizle(str(sonuc.raw)), giris, cikis
