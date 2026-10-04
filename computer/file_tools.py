"""Arquivos do Du: criar, ler, acrescentar, renomear, compactar e mandar para a Lixeira.

Pastas faladas ("documentos", "downloads", "área de trabalho"...) viram as pastas
reais do Windows (SHGetKnownFolderPath: funciona com OneDrive e pastas movidas).
Tudo que escreve, move ou apaga passa por ``guard_project_source`` (o código do
próprio TELEX não muda por aqui) e recusa pastas do sistema.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .assistant_tools import KNOWN_FOLDERS
from .workspace import guard_project_source

IS_WINDOWS = sys.platform.startswith("win")

# GUIDs das pastas conhecidas do Windows (FOLDERID_*).
_KNOWN_FOLDER_IDS: dict[str, str] = {
    "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}
FOLDER_ALIASES: dict[str, str] = {
    **KNOWN_FOLDERS,
    "area de trabalho": "Desktop", "área de trabalho": "Desktop", "documento": "Documents",
    "imagem": "Pictures", "video": "Videos", "vídeo": "Videos", "musica": "Music", "música": "Music",
}
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
)
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME = 120
MAX_TEXT_BYTES = 20 * 1024 * 1024
MAX_UNZIP_BYTES = 4 * 1024**3
MAX_UNZIP_FILES = 20000


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    return " ".join("".join(c for c in normalized if not unicodedata.combining(c)).split())


def _windows_known_folder(name: str) -> Path | None:
    if not IS_WINDOWS or name not in _KNOWN_FOLDER_IDS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        guid = GUID()
        ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
        if ole32.CLSIDFromString(ctypes.c_wchar_p(_KNOWN_FOLDER_IDS[name]), ctypes.byref(guid)) != 0:
            return None
        pointer = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)) != 0:
            return None
        try:
            return Path(pointer.value) if pointer.value else None
        finally:
            ole32.CoTaskMemFree(pointer)
    except Exception:
        return None


def known_folder(alias: str) -> Path | None:
    """"documentos" -> pasta Documentos real (None se não for um apelido conhecido)."""
    key = " ".join((alias or "").casefold().split())
    if key not in FOLDER_ALIASES:
        key = _plain(alias)
        if key not in FOLDER_ALIASES:
            return None
    folder = FOLDER_ALIASES[key]
    if not folder:
        return Path.home()
    return _windows_known_folder(folder) or Path.home() / folder


def sanitize_filename(name: str, default_ext: str = "") -> str:
    """Nome de arquivo seguro: sem separadores, caracteres proibidos nem nomes reservados.

    Levanta ValueError se não sobrar nada.
    """
    text = _INVALID_CHARS.sub(" ", str(name or ""))
    text = " ".join(text.split()).strip(" .")
    if not text:
        raise ValueError("Nome de arquivo vazio ou inválido.")
    stem, dot, _ext = text.rpartition(".")
    if not dot:
        stem = text
    if stem.casefold() in _RESERVED_NAMES or text.casefold() in _RESERVED_NAMES:
        text = "_" + text
    if default_ext and not dot:
        text += default_ext
    if len(text) > MAX_NAME:
        suffix = Path(text).suffix[:16]
        text = text[: MAX_NAME - len(suffix)].rstrip(" .") + suffix
    return text


def _system_dirs() -> list[Path]:
    dirs: list[str] = []
    if IS_WINDOWS:
        for variable in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
            value = os.environ.get(variable)
            if value:
                dirs.append(value)
        drive = os.environ.get("SystemDrive", "C:")
        dirs += [drive + "\\Windows", drive + "\\Program Files", drive + "\\Program Files (x86)", drive + "\\ProgramData"]
    else:
        dirs += ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/sbin", "/sys", "/usr", "/var/lib"]
    result: list[Path] = []
    for item in dirs:
        try:
            result.append(Path(item).resolve())
        except OSError:
            continue
    return result


def is_system_path(path: str | Path) -> bool:
    try:
        target = Path(path).expanduser().resolve()
    except OSError:
        return True
    if IS_WINDOWS and len(target.parts) <= 1:  # a raiz do disco (C:\)
        return True
    if not IS_WINDOWS and target == Path("/"):
        return True
    for base in _system_dirs():
        try:
            target.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def guard_write(path: str | Path, action: str = "alterar") -> None:
    """Recusa (PermissionError) o código do TELEX e as pastas do sistema."""
    guard_project_source(path, action)
    if is_system_path(path):
        raise PermissionError(f"Não posso {action} arquivos de pastas do sistema ({path}).")


def _member_escapes(name: str, destination: Path) -> bool:
    """Um item do zip sairia da pasta de destino (zip-slip)?"""
    if not name or "\x00" in name:
        return True
    for flavor in (PurePosixPath(name), PureWindowsPath(name)):
        if flavor.is_absolute() or flavor.anchor or ".." in flavor.parts:
            return True
    target = (destination / name).resolve()
    try:
        target.relative_to(destination.resolve())
    except ValueError:
        return True
    return False


def _error(message: str, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": message, "message": message, **extra}


class FileTools:
    """Ferramentas de arquivos para o agente (contrato igual ao de AssistantTools)."""

    def __init__(self, folders: dict[str, str | Path] | None = None) -> None:
        # Sobrescreve pastas (testes): {"documentos": "/tmp/x", ...}.
        self.folders = {" ".join(k.casefold().split()): Path(v) for k, v in (folders or {}).items()}

    # pastas --------------------------------------------------------------------
    def resolve_folder(self, folder: str = "documentos") -> Path:
        key = " ".join((folder or "documentos").casefold().split())
        if key in self.folders:
            return self.folders[key]
        if _plain(key) in self.folders:
            return self.folders[_plain(key)]
        if self.folders and (key in FOLDER_ALIASES or _plain(key) in FOLDER_ALIASES):
            target = FOLDER_ALIASES.get(key, FOLDER_ALIASES.get(_plain(key), ""))
            for alias, path in self.folders.items():
                if FOLDER_ALIASES.get(alias) == target:
                    return path
        known = known_folder(folder or "documentos")
        if known is not None:
            return known
        path = Path(folder).expanduser()
        if not path.is_absolute():
            raise ValueError(
                f"Pasta desconhecida: {folder}. Use documentos, downloads, área de trabalho, "
                "imagens, músicas, vídeos ou um caminho completo."
            )
        return path

    def _resolve_file(self, name_or_path: str, folder: str = "documentos") -> Path:
        candidate = Path(str(name_or_path or "").strip()).expanduser()
        if not str(candidate) or str(candidate) == ".":
            raise ValueError("Diga o nome do arquivo.")
        if candidate.is_absolute():
            return candidate
        base = self.resolve_folder(folder)
        target = (base / candidate).resolve()
        try:
            target.relative_to(base.resolve())
        except ValueError as exc:
            raise PermissionError("O arquivo precisa ficar dentro da pasta indicada.") from exc
        return target

    # texto ---------------------------------------------------------------------
    def save_text_file(self, name: str, content: str, folder: str = "documentos", overwrite: bool = False) -> dict[str, Any]:
        try:
            base = self.resolve_folder(folder)
            filename = sanitize_filename(name, ".txt")
            target = base / filename
            guard_write(target, "salvar")
        except (ValueError, PermissionError) as exc:
            return _error(str(exc))
        if target.exists() and not overwrite:
            return _error(f"Já existe {filename} em {base}. Peça para sobrescrever se quiser substituir.", path=str(target), exists=True)
        if target.exists() and not target.is_file():
            return _error(f"{target} é uma pasta, não um arquivo.")
        base.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(str(content or ""), encoding="utf-8")
        verb = "Substituí" if existed else "Salvei"
        return {"message": f"{verb} {filename} em {base.name or base}.", "path": str(target), "bytes": target.stat().st_size, "overwritten": existed}

    def append_text_file(self, path_or_name: str, content: str, folder: str = "documentos") -> dict[str, Any]:
        try:
            target = self._resolve_file(path_or_name, folder)
            if not Path(str(path_or_name)).expanduser().is_absolute():
                target = target.with_name(sanitize_filename(target.name))
            if not target.suffix and not target.exists():
                target = target.with_name(target.name + ".txt")
            guard_write(target, "alterar")
        except (ValueError, PermissionError) as exc:
            return _error(str(exc))
        if target.exists() and not target.is_file():
            return _error(f"{target} é uma pasta, não um arquivo.")
        created = not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        text = str(content or "")
        if not created and target.stat().st_size:
            with target.open("rb") as handle:
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) not in (b"\n", b"\r"):
                    text = "\n" + text
        with target.open("a", encoding="utf-8") as handle:
            handle.write(text)
        action = "Criei" if created else "Acrescentei o texto em"
        return {"message": f"{action} {target.name}.", "path": str(target), "created": created}

    def read_text_file(self, name_or_path: str, folder: str = "documentos", max_chars: int = 20000) -> dict[str, Any]:
        try:
            target = self._resolve_file(name_or_path, folder)
        except (ValueError, PermissionError) as exc:
            return _error(str(exc))
        if not target.exists() and not target.suffix and target.with_suffix(".txt").exists():
            target = target.with_suffix(".txt")
        if not target.is_file():
            return _error(f"Arquivo não encontrado: {target}")
        if target.stat().st_size > MAX_TEXT_BYTES:
            return _error(f"{target.name} é grande demais para ler como texto.")
        raw = target.read_bytes()
        if b"\x00" in raw[:4096]:
            return _error(f"{target.name} não é um arquivo de texto.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        limit = max(1, int(max_chars or 20000))
        truncated = len(text) > limit
        return {
            "message": f"Li {target.name}" + (f" (primeiros {limit} caracteres)." if truncated else "."),
            "path": str(target), "content": text[:limit], "truncated": truncated, "chars": len(text),
        }

    # pastas e listagens -------------------------------------------------------------
    def recent_files(self, folder: str = "downloads", limit: int = 10) -> dict[str, Any]:
        try:
            base = self.resolve_folder(folder)
        except ValueError as exc:
            return _error(str(exc))
        if not base.is_dir():
            return _error(f"Pasta não encontrada: {base}")
        entries: list[tuple[float, Path, int]] = []
        for item in base.iterdir():
            if item.name.startswith(".") or item.name.casefold() in {"desktop.ini", "thumbs.db"}:
                continue
            try:
                if item.is_file():
                    stat = item.stat()
                    entries.append((stat.st_mtime, item, stat.st_size))
            except OSError:
                continue
        entries.sort(key=lambda entry: entry[0], reverse=True)
        files = [
            {"name": path.name, "path": str(path), "size": size, "modified": datetime.fromtimestamp(mtime).isoformat(timespec="minutes")}
            for mtime, path, size in entries[: max(1, int(limit or 10))]
        ]
        if not files:
            return {"message": f"Não há arquivos em {base.name or base}.", "folder": str(base), "files": []}
        names = ", ".join(item["name"] for item in files[:5])
        return {"message": f"Os mais recentes em {base.name or base}: {names}.", "folder": str(base), "files": files}

    def create_folder(self, name: str, parent: str = "documentos") -> dict[str, Any]:
        try:
            base = self.resolve_folder(parent)
            target = base / sanitize_filename(name)
            guard_write(target, "criar pastas em")
        except (ValueError, PermissionError) as exc:
            return _error(str(exc))
        if target.exists() and not target.is_dir():
            return _error(f"Já existe um arquivo chamado {target.name}.")
        existed = target.is_dir()
        target.mkdir(parents=True, exist_ok=True)
        message = f"A pasta {target.name} já existia." if existed else f"Criei a pasta {target.name} em {base.name or base}."
        return {"message": message, "path": str(target), "created": not existed}

    def rename_file(self, path: str, new_name: str) -> dict[str, Any]:
        try:
            source = self._resolve_file(path, "documentos")
            if not source.exists():
                return _error(f"Não encontrei {source}.")
            cleaned = sanitize_filename(new_name)
            if source.is_file() and source.suffix and not Path(cleaned).suffix:
                cleaned += source.suffix  # mantém a extensão: "relatorio" -> "relatorio.pdf"
            target = source.with_name(cleaned)
            guard_write(source, "renomear")
            guard_write(target, "renomear")
        except (ValueError, PermissionError) as exc:
            return _error(str(exc))
        if target == source:
            return {"message": f"{source.name} já tem esse nome.", "path": str(source)}
        if target.exists() and target.name.casefold() != source.name.casefold():
            return _error(f"Já existe {target.name} nessa pasta.")
        source.rename(target)
        return {"message": f"Renomeei {source.name} para {target.name}.", "path": str(target), "old_path": str(source)}

    # zip -----------------------------------------------------------------------
    def zip_files(self, paths: list[str] | str, zip_name: str, folder: str = "documentos") -> dict[str, Any]:
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            return _error("Diga quais arquivos compactar.")
        try:
            base = self.resolve_folder(folder)
            sources = [self._resolve_file(item, folder) for item in paths]
            name = sanitize_filename(zip_name)
            if not name.casefold().endswith(".zip"):
                name += ".zip"
            target = base / name
            guard_write(target, "criar")
        except (ValueError, PermissionError) as exc:
            return _error(str(exc))
        missing = [str(item) for item in sources if not item.exists()]
        if missing:
            return _error("Não encontrei: " + ", ".join(missing))
        if target.exists():
            return _error(f"Já existe {target.name}. Escolha outro nome.")
        base.mkdir(parents=True, exist_ok=True)
        count = 0
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source in sources:
                if source.is_dir():
                    for current, dirs, files in os.walk(source):
                        dirs.sort()
                        for file in sorted(files):
                            item = Path(current) / file
                            if item.resolve() == target.resolve():
                                continue
                            archive.write(item, str(Path(source.name) / item.relative_to(source)))
                            count += 1
                else:
                    archive.write(source, source.name)
                    count += 1
        return {"message": f"Compactei {count} arquivo(s) em {target.name}.", "path": str(target), "files": count}

    def unzip_file(self, path: str, destination: str = "") -> dict[str, Any]:
        try:
            source = self._resolve_file(path, "documentos")
            if not source.is_file():
                return _error(f"Não encontrei {source}.")
            if destination:
                dest = Path(destination).expanduser()
                if not dest.is_absolute():
                    known = known_folder(destination)
                    dest = known if known is not None else source.parent / sanitize_filename(destination)
            else:
                dest = source.parent / sanitize_filename(source.stem or "extraido")
                counter = 2
                while dest.exists():
                    dest = source.parent / f"{source.stem} ({counter})"
                    counter += 1
            guard_write(dest, "extrair")
        except (ValueError, PermissionError) as exc:
            return _error(str(exc))
        try:
            archive = zipfile.ZipFile(source)
        except zipfile.BadZipFile:
            return _error(f"{source.name} não é um zip válido.")
        with archive:
            members = archive.infolist()
            if len(members) > MAX_UNZIP_FILES or sum(m.file_size for m in members) > MAX_UNZIP_BYTES:
                return _error(f"{source.name} é grande demais para extrair com segurança.")
            unsafe = [m.filename for m in members if _member_escapes(m.filename, dest)]
            if unsafe:
                return _error(f"Recusei extrair {source.name}: itens tentam sair da pasta de destino ({unsafe[0]}).", unsafe=unsafe[:10])
            conflicts = [m.filename for m in members if not m.is_dir() and (dest / m.filename).exists()]
            if conflicts:
                return _error(f"Já existem arquivos com esses nomes em {dest}: {', '.join(conflicts[:5])}.")
            dest.mkdir(parents=True, exist_ok=True)
            archive.extractall(dest)
        count = sum(1 for m in members if not m.is_dir())
        return {"message": f"Extraí {count} arquivo(s) para {dest.name}.", "path": str(dest), "files": count}

    # lixeira -------------------------------------------------------------------
    def move_to_trash(self, path: str) -> dict[str, Any]:
        try:
            target = self._resolve_file(path, "documentos")
            guard_write(target, "apagar")
        except (ValueError, PermissionError) as exc:
            return _error(str(exc))
        if not target.exists():
            return _error(f"Não encontrei {target}.")
        if not IS_WINDOWS:
            raise RuntimeError("Mandar para a Lixeira só funciona no Windows.")
        code = _recycle(target)
        if code != 0 or target.exists():
            return _error(f"O Windows não conseguiu mandar {target.name} para a Lixeira (código {code}).")
        return {"message": f"Mandei {target.name} para a Lixeira (dá para restaurar de lá).", "path": str(target)}

    # registro --------------------------------------------------------------------
    SPECS: list[tuple[str, str, tuple[str, ...], dict[str, Any]]] = [
        ("save_text_file", "Cria um arquivo de texto (UTF-8) numa pasta (documentos, downloads, área de trabalho...); não sobrescreve sem overwrite=true", ("name", "content"), {"name": str, "content": str, "folder": str, "overwrite": bool}),
        ("append_text_file", "Acrescenta texto ao fim de um arquivo (cria se não existir)", ("path_or_name", "content"), {"path_or_name": str, "content": str, "folder": str}),
        ("read_text_file", "Lê um arquivo de texto (pelo nome numa pasta ou caminho completo)", ("name_or_path",), {"name_or_path": str, "folder": str, "max_chars": int}),
        ("recent_files", "Lista os arquivos mais recentes de uma pasta (padrão: downloads), com tamanho e data", (), {"folder": str, "limit": int}),
        ("create_folder", "Cria uma pasta dentro de outra (padrão: documentos)", ("name",), {"name": str, "parent": str}),
        ("rename_file", "Renomeia um arquivo ou pasta, na mesma pasta (mantém a extensão se omitida)", ("path", "new_name"), {"path": str, "new_name": str}),
        ("zip_files", "Compacta arquivos/pastas num .zip salvo na pasta indicada", ("paths", "zip_name"), {"paths": (list, str), "zip_name": str, "folder": str}),
        ("unzip_file", "Extrai um .zip (padrão: pasta com o nome do zip ao lado dele)", ("path",), {"path": str, "destination": str}),
        ("move_to_trash", "Manda um arquivo ou pasta para a Lixeira do Windows", ("path",), {"path": str}),
    ]
    RISK: dict[str, str] = {
        "save_text_file": "medium", "append_text_file": "medium", "read_text_file": "low",
        "recent_files": "low", "create_folder": "low", "rename_file": "medium",
        "zip_files": "medium", "unzip_file": "medium", "move_to_trash": "high",
    }

    def register(self, executor: Any, schemas: Any | None = None) -> None:
        from brain.tool_schema import ToolSpec

        for name, description, required, types in self.SPECS:
            executor.register(name, getattr(self, name))
            if schemas is not None:
                schemas.register(ToolSpec(name, description, required, types))


def _recycle(target: Path) -> int:
    """SHFileOperationW(FO_DELETE, FOF_ALLOWUNDO): vai para a Lixeira, sem diálogo."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR), ("fFlags", wintypes.WORD), ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    operation = SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = str(target.resolve()) + "\0"  # lista terminada em dois nulos
    operation.pTo = None
    operation.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400  # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    code = int(shell32.SHFileOperationW(ctypes.byref(operation)))
    if operation.fAnyOperationsAborted:
        return code or -1
    return code
