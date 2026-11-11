import threading

import pytest

from plaza.hatalar import Durduruldu
from plaza.orchestrator import Adim, IsAkisi, _temizle
from plaza.settings import load_office


def _akis(tmp_path, ayar_dosyasi, **kw):
    olaylar = []
    a = IsAkisi(load_office(ayar_dosyasi=ayar_dosyasi), "Test talebi", lambda tip, **v: olaylar.append((tip, v)),
                tmp_path, simulasyon=True, **kw)
    return a, olaylar


def test_simulasyon_tam_akis(hizli, tmp_path, ayar_dosyasi):
    a, olaylar = _akis(tmp_path, ayar_dosyasi, max_revizyon=1)
    sonuc = a.calistir()
    tipler = [t for t, _ in olaylar]
    assert "Nihai Teslimat" in sonuc
    assert tipler[0] == "durum" and "plan" in tipler
    plan = next(v for t, v in olaylar if t == "plan")
    assert len({x["asama"] for x in plan["adimlar"]}) == 3  # hazırlık, paralel orta, toparlama
    assert any(t == "degerlendirme" and not v["onay"] for t, v in olaylar)  # bir revizyon turu
    assert len(a.kayit()["tamamlanan"]) == len(plan["adimlar"])


def test_kaldigi_yerden_devam_biten_adimlari_tekrarlamaz(hizli, tmp_path, ayar_dosyasi):
    a, _ = _akis(tmp_path, ayar_dosyasi, max_revizyon=0)
    a.calistir()
    kayit = a.kayit()
    kayit["tamamlanan"] = kayit["tamamlanan"][:-1]  # son adım yarıda kalmış gibi
    eksik = a.kayit()["tamamlanan"][-1][0]
    b, olaylar = _akis(tmp_path, ayar_dosyasi, max_revizyon=0, devam=kayit)
    b.calistir()
    atananlar = [v["kime"] for t, v in olaylar if t == "gorev_atandi"]
    assert atananlar == [eksik]
    assert next(v for t, v in olaylar if t == "plan")["devam"] is True


def test_durdurma(hizli, tmp_path, ayar_dosyasi):
    iptal = threading.Event()
    iptal.set()
    a, _ = _akis(tmp_path, ayar_dosyasi, iptal=iptal)
    with pytest.raises(Durduruldu):
        a.calistir()


def test_plan_onayi_duzenlenmis_plani_kullanir(hizli, tmp_path, ayar_dosyasi):
    a, olaylar = _akis(tmp_path, ayar_dosyasi, max_revizyon=0, plan_onayi=True)
    t = threading.Thread(target=a.calistir)
    t.start()
    for _ in range(200):
        if a.onay_bekliyor and any(x == "plan_onay_bekleniyor" for x, _ in olaylar):
            break
        threading.Event().wait(0.01)
    a.plani_onayla([{"calisan": "yazilimci", "gorev": "Sadece kodu yaz", "asama": 1}])
    t.join(timeout=10)
    assert [v["kime"] for x, v in olaylar if x == "gorev_atandi"] == ["yazilimci"]


def test_gecici_hatada_yeniden_dener_kalicida_yedege_gecer(hizli, tmp_path, ayar_dosyasi, monkeypatch):
    office = load_office(ayar_dosyasi=ayar_dosyasi)
    office.desk("yazilimci").yedek_model = "ollama/yedek"
    olaylar = []
    a = IsAkisi(office, "t", lambda tip, **v: olaylar.append((tip, v)), tmp_path, simulasyon=False)
    cagrilar = []

    def sahte_calisan(desk, gorev, tur, onceki, model=None):
        cagrilar.append(model)
        if len(cagrilar) == 1:
            raise Exception("503 UNAVAILABLE high demand")          # geçici → aynı model yeniden
        if model != "ollama/yedek":
            raise Exception("429 limit: 0, model: x, per day")     # kalıcı → yedek modele geç
        return "çıktı", 10, 5

    monkeypatch.setattr(a, "_calisan", sahte_calisan)
    a._tek_adim(Adim("yazilimci", "görev"), 0, {})
    assert cagrilar == [office.desk("yazilimci").model, office.desk("yazilimci").model, "ollama/yedek"]
    bitti = next(v for t, v in olaylar if t == "gorev_bitti")
    assert bitti["model"] == "ollama/yedek" and bitti["maliyet"] == 0


def test_adim_dogrulama_asamalari_sikistirir(tmp_path, ayar_dosyasi):
    a, _ = _akis(tmp_path, ayar_dosyasi)
    adimlar = a._adimlari_dogrula([
        {"calisan": "yazilimci", "gorev": "b", "asama": 7},
        {"calisan": "olmayan", "gorev": "x", "asama": 1},
        {"calisan": "urun_yoneticisi", "gorev": "a", "asama": 3},
        {"calisan": "qa", "gorev": "  ", "asama": 1},
    ])
    assert [(x.calisan, x.asama) for x in adimlar] == [("urun_yoneticisi", 1), ("yazilimci", 2)]


def test_temizle():
    assert _temizle("<think>uzun düşünce {x}</think>\nsonuç") == "sonuç"
    assert _temizle("düşünce</think>cevap") == "cevap"
    assert _temizle("```markdown\n# Başlık\nmetin\n```") == "# Başlık\nmetin"
    assert _temizle("normal") == "normal"
