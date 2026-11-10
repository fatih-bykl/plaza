"""Ajanların kullandığı dosya araçları.

Tüm araçlar yalnızca çalışma klasörünün (varsayılan: ./cikti) içinde çalışır;
ajanlar bu klasörün dışına okuma/yazma yapamaz.
"""

from __future__ import annotations

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


TOOL_TYPES: dict[str, type[_Workspace]] = {
    "file_read": FileReadTool,
    "file_write": FileWriteTool,
    "list_files": ListFilesTool,
}


def build_tools(names: list[str], root: Path) -> list[BaseTool]:
    unknown = set(names) - TOOL_TYPES.keys()
    if unknown:
        raise ValueError(f"Bilinmeyen araç(lar): {', '.join(sorted(unknown))}")
    return [TOOL_TYPES[n](root) for n in names]
