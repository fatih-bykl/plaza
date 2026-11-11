"""Ajanların kullandığı araçlar.

- Dosya araçları yalnızca çalışma klasörünün (cikti/<iş>) içinde çalışır.
- web_ara / web_oku: internette arama ve sayfa okuma (yerel ağ adresleri engellenir).
- python_calistir: Python kodunu çalışma klasöründe, zaman sınırıyla ve API anahtarları
  olmadan çalıştırır. Kod bilgisayarınızda çalıştığı için varsayılan olarak kapalıdır;
  masa ayarlarından bilerek açılır.
"""

from __future__ import annotations

import html
import ipaddress
import os
import re
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr


class _Workspace(BaseTool):
    _root: Path = PrivateAttr()

    def __init__(self, root: Path, **kwargs):
        super().__init__(**kwargs)
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe(self, rel: str) -> Path:
        path = (self._root / rel).resolve()
        if path != self._root and self._root not in path.parents:
            raise ValueError(f"'{rel}' çalışma klasörünün dışında.")
        return path


class _PathArgs(BaseModel):
    path: str = Field(description="Çalışma klasörüne göre dosya yolu, örn. 'rapor.md' veya 'src/app.py'")


class _WriteArgs(_PathArgs):
    content: str = Field(description="Dosyaya yazılacak tam içerik")


class _ListArgs(BaseModel):
    path: str = Field(default=".", description="Listelenecek klasör (varsayılan: kök)")


class FileReadTool(_Workspace):
    name: str = "file_read"
    description: str = "Çalışma klasöründeki bir dosyanın içeriğini okur."
    args_schema: type[BaseModel] = _PathArgs

    def _run(self, path: str) -> str:
        try:
            return self._safe(path).read_text(encoding="utf-8")
        except Exception as e:  # ajana hatayı metin olarak döndür
            return f"HATA: {e}"


class FileWriteTool(_Workspace):
    name: str = "file_write"
    description: str = "Çalışma klasörüne dosya yazar (varsa üzerine yazar, klasörleri oluşturur)."
    args_schema: type[BaseModel] = _WriteArgs

    def _run(self, path: str, content: str) -> str:
        try:
            target = self._safe(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Yazıldı: {target.relative_to(self._root)} ({len(content)} karakter)"
        except Exception as e:
            return f"HATA: {e}"


class ListFilesTool(_Workspace):
    name: str = "list_files"
    description: str = "Çalışma klasöründeki dosyaları listeler."
    args_schema: type[BaseModel] = _ListArgs

    def _run(self, path: str = ".") -> str:
        try:
            base = self._safe(path)
            files = sorted(str(p.relative_to(self._root)) for p in base.rglob("*") if p.is_file())
            return "\n".join(files) or "(boş)"
        except Exception as e:
            return f"HATA: {e}"


# ------------------------------------------------------------------ web
_TARAYICI = "Mozilla/5.0 (X11; Linux x86_64) PlazaOfis/1.0"
_MAX_SAYFA = 1_500_000  # bayt
_MAX_METIN = 8000       # karakter


def _guvenli_url(url: str) -> str:
    """Yalnızca http(s) ve herkese açık adreslere izin ver (yerel ağ / bu bilgisayar engellenir)."""
    p = urllib.parse.urlparse(url.strip())
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Yalnızca http:// veya https:// adresleri okunabilir.")
    for bilgi in socket.getaddrinfo(p.hostname, None):
        ip = ipaddress.ip_address(bilgi[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Yerel ağ ya da bu bilgisayardaki adresler okunamaz.")
    return url.strip()


class _GuvenliYonlendirme(urllib.request.HTTPRedirectHandler):
    """Yönlendirmeler de yerel adreslere gidemesin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _guvenli_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_ACICI = urllib.request.build_opener(_GuvenliYonlendirme)


def _getir(url: str, veri: bytes | None = None) -> str:
    istek = urllib.request.Request(_guvenli_url(url), data=veri, headers={"User-Agent": _TARAYICI})
    with _ACICI.open(istek, timeout=20) as r:
        ham = r.read(_MAX_SAYFA)
        kod = r.headers.get_content_charset() or "utf-8"
    return ham.decode(kod, errors="replace")


def _html_metin(sayfa: str) -> str:
    sayfa = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", sayfa)
    sayfa = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", sayfa)
    metin = html.unescape(re.sub(r"<[^>]+>", " ", sayfa))
    metin = re.sub(r"[ \t\r\f\v]+", " ", metin)
    return re.sub(r"\n\s*\n+", "\n\n", metin).strip()


class _AramaArgs(BaseModel):
    sorgu: str = Field(description="Aranacak ifade, örn. 'kahve dükkanı web sitesi örnekleri 2026'")


class _UrlArgs(BaseModel):
    url: str = Field(description="Okunacak sayfanın tam adresi (https://...)")


class WebSearchTool(_Workspace):
    name: str = "web_ara"
    description: str = (
        "İnternette arama yapar; ilk sonuçların başlığını, adresini ve kısa özetini döndürür. "
        "Ayrıntı için ilgili adresi web_oku ile oku."
    )
    args_schema: type[BaseModel] = _AramaArgs

    def _run(self, sorgu: str) -> str:
        try:
            sayfa = _getir("https://html.duckduckgo.com/html/",
                           urllib.parse.urlencode({"q": sorgu, "kl": "tr-tr"}).encode())
        except Exception as e:
            return f"HATA: arama yapılamadı ({e})"
        sonuclar = []
        bloklar = re.findall(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)',
                             sayfa)
        for href, baslik, geri in bloklar[:8]:
            if "uddg=" in href:
                href = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0])
            ozet = re.search(r'(?is)class="result__snippet"[^>]*>(.*?)</a>', geri)
            sonuclar.append(
                f"- {_html_metin(baslik)}\n  {href}\n  {_html_metin(ozet.group(1)) if ozet else ''}".rstrip())
        return "\n".join(sonuclar) or "Sonuç bulunamadı (arama servisi yanıt vermemiş olabilir)."


class WebReadTool(_Workspace):
    name: str = "web_oku"
    description: str = "Bir web sayfasını açar ve metnini (en fazla 8000 karakter) döndürür."
    args_schema: type[BaseModel] = _UrlArgs

    def _run(self, url: str) -> str:
        try:
            metin = _html_metin(_getir(url))
        except Exception as e:
            return f"HATA: sayfa okunamadı ({e})"
        return metin[:_MAX_METIN] + ("\n…(kısaltıldı)" if len(metin) > _MAX_METIN else "")


# ------------------------------------------------------------------ python
class _KodArgs(BaseModel):
    kod: str = Field(description="Çalıştırılacak Python kodu. Çıktı için print kullan.")


class PythonRunTool(_Workspace):
    name: str = "python_calistir"
    description: str = (
        "Python kodunu çalışma klasöründe çalıştırır (en fazla 30 sn) ve çıktısını döndürür. "
        "Hesaplama yapmak ve yazdığın kodu test etmek için kullan; dosyalar çalışma klasörüne göre okunur/yazılır."
    )
    args_schema: type[BaseModel] = _KodArgs

    def _run(self, kod: str) -> str:
        dosya = self._root / "_plaza_calistir.py"
        try:
            dosya.write_text(kod, encoding="utf-8")
            # API anahtarları ve diğer gizli ortam değişkenleri alt sürece aktarılmaz
            ortam = {"PATH": os.environ.get("PATH", ""), "HOME": str(self._root), "LANG": "C.UTF-8",
                     "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, "-I", str(dosya)], cwd=self._root, env=ortam,
                               capture_output=True, text=True, timeout=30)
            cikti = (r.stdout or "") + (f"\n[stderr]\n{r.stderr}" if r.stderr else "")
            return (f"(çıkış kodu {r.returncode})\n" + cikti)[:6000] or "(çıktı yok)"
        except subprocess.TimeoutExpired:
            return "HATA: kod 30 saniyede bitmedi ve durduruldu."
        except Exception as e:
            return f"HATA: {e}"
        finally:
            dosya.unlink(missing_ok=True)


TOOL_TYPES: dict[str, type[_Workspace]] = {
    "file_read": FileReadTool,
    "file_write": FileWriteTool,
    "list_files": ListFilesTool,
    "web_ara": WebSearchTool,
    "web_oku": WebReadTool,
    "python_calistir": PythonRunTool,
}


def build_tools(names: list[str], root: Path) -> list[BaseTool]:
    unknown = set(names) - TOOL_TYPES.keys()
    if unknown:
        raise ValueError(f"Bilinmeyen araç(lar): {', '.join(sorted(unknown))}")
    return [TOOL_TYPES[n](root) for n in names]
