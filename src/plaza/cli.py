"""Plaza komut satırı arayüzü."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    p = argparse.ArgumentParser(prog="plaza", description="Claude destekli çok departmanlı ajan ofisi.")
    p.add_argument("talep", nargs="?", help="Plaza'ya verilecek iş (boşsa sorulur)")
    p.add_argument(
        "-s", "--surec", choices=["hiyerarsik", "sirali"], default="hiyerarsik",
        help="hiyerarsik: Genel Müdür işi dağıtır | sirali: çalışanlar sırayla çalışır",
    )
    p.add_argument(
        "-d", "--departman", action="append", metavar="ANAHTAR",
        help="Yalnızca bu departman(lar)ı kullan; sıralı modda sıra da budur (tekrarlanabilir). Örn: -d urun -d yazilim -d kalite",
    )
    p.add_argument("-o", "--cikti", default="cikti", help="Ajanların dosya yazacağı klasör (varsayılan: cikti)")
    p.add_argument("--org", type=Path, help="Özel bir departments.yaml dosyası")
    p.add_argument("--liste", action="store_true", help="Departmanları ve çalışanları listele, çık")
    p.add_argument("--kuru", action="store_true", help="Ekibi kur ama Claude'u çağırma (deneme)")
    p.add_argument("-q", "--sessiz", action="store_true", help="Ayrıntılı ajan günlüğünü kapat")
    a = p.parse_args(argv)

    from .office import build_crew, list_staff, load_org

    if a.liste:
        org = load_org(a.org)
        for key, d in org["departments"].items():
            print(f"{key:<10} {d['name']}")
            for s in d["staff"]:
                print(f"           - {s['role']}  araçlar: {', '.join(s.get('tools', [])) or '-'}")
        return 0

    talep = a.talep or input("Plaza'ya talebiniz: ").strip()
    if not talep:
        p.error("Bir talep girmelisiniz.")

    if not a.kuru and not (os.getenv("ANTHROPIC_API_KEY")):
        print("HATA: ANTHROPIC_API_KEY tanımlı değil. .env.example dosyasını .env olarak kopyalayıp anahtarınızı yazın.",
              file=sys.stderr)
        return 2

    process = "hierarchical" if a.surec == "hiyerarsik" else "sequential"
    try:
        crew = build_crew(
            talep, process=process, departments=a.departman, workdir=Path(a.cikti),
            org_file=a.org, verbose=not a.sessiz,
        )
    except ValueError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2

    if a.kuru:
        print(f"Süreç: {process}")
        print("Çalışanlar:", ", ".join(ag.role for ag in crew.agents))
        if crew.manager_agent:
            print("Yönetici:", crew.manager_agent.role, f"({crew.manager_agent.llm.model})")
        print("Görev sayısı:", len(crew.tasks))
        print("Kuru çalıştırma tamam; Claude çağrılmadı.")
        return 0

    import anthropic

    try:
        result = crew.kickoff()
    except anthropic.APIStatusError as e:
        msg = e.body.get("error", {}).get("message", str(e)) if isinstance(e.body, dict) else str(e)
        print(f"\nHATA: Claude API {e.status_code}: {msg}", file=sys.stderr)
        if "credit balance" in msg:
            print("Çözüm: platform.claude.com → Settings → Billing bölümünden kredi yükleyin.", file=sys.stderr)
        return 3
    except anthropic.APIConnectionError:
        print("\nHATA: Claude API'ye bağlanılamadı (internet bağlantısını kontrol edin).", file=sys.stderr)
        return 3
    out = Path(a.cikti)
    out.mkdir(parents=True, exist_ok=True)
    (out / "SONUC.md").write_text(str(result.raw), encoding="utf-8")
    print("\n" + "=" * 60 + "\nNİHAİ SONUÇ\n" + "=" * 60)
    print(result.raw)
    print(f"\nKaydedildi: {out / 'SONUC.md'}")
    if result.token_usage:
        print(f"Token kullanımı: {result.token_usage}")
    return 0
