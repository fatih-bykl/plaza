"""Plaza komut satırı arayüzü.

Ofis arayüzüyle aynı ayarları (departments.yaml + ofis.json) ve aynı CEO akışını kullanır:
talep CEO'ya gelir, CEO planlar, departmanlar aşama aşama çalışır, CEO değerlendirip teslim eder.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


def _yaz(metin: str, sessiz: bool) -> None:
    if not sessiz:
        print(metin, flush=True)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    p = argparse.ArgumentParser(prog="plaza", description="Claude destekli çok departmanlı ajan ofisi (CEO akışı).")
    p.add_argument("talep", nargs="?", help="Plaza'ya verilecek iş (boşsa sorulur)")
    p.add_argument(
        "-d", "--departman", action="append", metavar="ANAHTAR",
        help="Yalnızca bu departman(lar)ın çalışanlarını kullan (tekrarlanabilir). Örn: -d urun -d yazilim",
    )
    p.add_argument("-r", "--revizyon", type=int, default=1, choices=range(0, 4), metavar="0-3",
                   help="CEO'nun isteyebileceği en fazla revizyon turu (varsayılan: 1)")
    p.add_argument("-o", "--cikti", default="cikti", help="Çıktı klasörü (varsayılan: cikti)")
    p.add_argument("--liste", action="store_true", help="Departmanları, çalışanları ve modellerini listele, çık")
    p.add_argument("--kuru", "--simulasyon", dest="kuru", action="store_true",
                   help="Simülasyon: akışı sahte çıktılarla çalıştır, yapay zekâ çağırma")
    p.add_argument("-q", "--sessiz", action="store_true", help="Yalnızca nihai sonucu yaz")
    a = p.parse_args(argv)

    from .hatalar import Durduruldu, turkce_mesaj
    from .orchestrator import IsAkisi
    from .settings import eksik_anahtarlar, load_office

    office = load_office()

    if a.liste:
        print(f"CEO        {office.ceo.isim}  [{office.ceo.model}]")
        for d in office.departments:
            print(f"{d.key:<10} {d.name}")
            for s in d.staff:
                durum = "" if s.aktif else "  (pasif)"
                print(f"           - {s.isim}, {s.role}  [{s.model}]  araçlar: {', '.join(s.tools) or '-'}{durum}")
        return 0

    if a.departman:
        bilinen = {d.key for d in office.departments}
        bilinmeyen = set(a.departman) - bilinen
        if bilinmeyen:
            p.error(f"Bilinmeyen departman(lar): {', '.join(sorted(bilinmeyen))}. Mevcut: {', '.join(sorted(bilinen))}")
        for d in office.departments:
            if d.key not in a.departman:
                for s in d.staff:
                    s.aktif = False
    if not office.aktif_calisanlar():
        p.error("Seçilen departmanlarda aktif çalışan yok.")

    talep = a.talep or input("Plaza'ya talebiniz: ").strip()
    if not talep:
        p.error("Bir talep girmelisiniz.")

    if not a.kuru:
        eksik = eksik_anahtarlar(office)
        if eksik:
            print("HATA: Bazı masaların yapay zekâsı hazır değil:\n  - " + "\n  - ".join(eksik), file=sys.stderr)
            print("Eksikleri giderin ya da --kuru ile simülasyon çalıştırın.", file=sys.stderr)
            return 2

    isimler = {"ceo": office.ceo.isim, **{s.key: s.isim for s in office.calisanlar()}}
    klasor = Path(a.cikti) / datetime.now().strftime("%Y%m%d-%H%M%S")

    def emit(tip: str, **v) -> None:
        if tip == "plan":
            _yaz(f"\n📋 Plan: {v['ozet']}", a.sessiz)
            for x in v["adimlar"]:
                _yaz(f"   {x['asama']}. aşama · {isimler.get(x['calisan'], x['calisan'])}: {x['gorev'][:100]}", a.sessiz)
        elif tip == "gorev_atandi":
            _yaz(f"→ {isimler.get(v['kime'], v['kime'])} çalışıyor…", a.sessiz)
        elif tip == "gorev_bitti":
            ek = f", {v['token']} token" if v.get("token") else ""
            _yaz(f"✓ {isimler.get(v['kime'], v['kime'])} bitirdi ({v['sure']} sn{ek})", a.sessiz)
        elif tip == "degerlendirme" and not v["onay"]:
            _yaz(f"↻ CEO revizyon istedi: {', '.join(isimler.get(r['calisan'], r['calisan']) for r in v['revizyonlar'])}",
                 a.sessiz)
        elif tip == "durum" and v.get("durum") == "bekliyor" and "sn" in v.get("aciklama", ""):
            _yaz(f"⏳ {isimler.get(v['masa'], v['masa'])}: {v['aciklama']}", a.sessiz)

    _yaz(f"Talep CEO'ya iletildi ({office.ceo.isim}){' — simülasyon' if a.kuru else ''}.", a.sessiz)
    akis = IsAkisi(office, talep, emit, klasor, simulasyon=a.kuru, max_revizyon=a.revizyon)
    try:
        sonuc = akis.calistir()
    except KeyboardInterrupt:
        print("\nDurduruldu.", file=sys.stderr)
        return 130
    except Durduruldu:
        print("\nDurduruldu.", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 — kullanıcıya Türkçe açıkla
        masa = getattr(e, "plaza_masa", None)
        print(f"\nHATA: {masa + ': ' if masa else ''}{turkce_mesaj(e)}", file=sys.stderr)
        return 3

    klasor.mkdir(parents=True, exist_ok=True)
    (klasor / "SONUC.md").write_text(sonuc, encoding="utf-8")
    if not a.sessiz:
        print("\n" + "=" * 60 + "\nNİHAİ SONUÇ\n" + "=" * 60)
    print(sonuc)
    ist = akis.ozet_istatistik()
    _yaz(f"\nKaydedildi: {klasor / 'SONUC.md'}  ·  {ist['toplam_token']} token"
         + (f"  ·  ${ist['toplam_maliyet']:.4f}" if ist["toplam_token"] else ""), a.sessiz)
    return 0
