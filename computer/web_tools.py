"""Ferramentas de web: ler o conteúdo de uma página, listar links, checar um
endereço e baixar arquivos para a pasta Downloads.

Só biblioteca padrão. Toda ferramenta devolve um dicionário com "message"
(frase curta em português) e os dados estruturados.

Segurança:
- só http/https; o host é resolvido e IPs privados/loopback/link-local são
  recusados (proteção contra SSRF), inclusive em cada redirecionamento;
- leitura limitada (3 MB para páginas, 500 MB para downloads);
- downloads nunca sobrescrevem e extensões executáveis são recusadas.
"""

from __future__ import annotations

import ipaddress
import mimetypes
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

IS_WINDOWS = sys.platform.startswith("win")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
TIMEOUT = 15.0
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
DOWNLOAD_DEADLINE = 30 * 60.0
CHUNK = 64 * 1024

EXECUTABLE_EXTENSIONS = frozenset({
    ".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr", ".lnk",
    ".hta", ".reg", ".jar", ".com", ".vbe", ".jse", ".wsf", ".wsh", ".pif",
    ".cpl", ".msp", ".appx", ".msix", ".psm1", ".dll", ".sys",
})

# Atalhos de pasta (mesmos nomes de computer/assistant_tools.KNOWN_FOLDERS).
FOLDER_ALIASES = {
    "downloads": "Downloads", "download": "Downloads",
    "documentos": "Documents", "documents": "Documents",
    "area de trabalho": "Desktop", "área de trabalho": "Desktop", "desktop": "Desktop",
    "imagens": "Pictures", "fotos": "Pictures", "pictures": "Pictures",
    "musicas": "Music", "músicas": "Music", "music": "Music",
    "videos": "Videos", "vídeos": "Videos",
}

WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}

SKIP_TAGS = frozenset({
    "script", "style", "nav", "footer", "header", "aside", "form", "svg",
    "noscript", "template", "iframe", "button", "select", "canvas", "object",
})
BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "br", "tr", "table", "ul", "ol",
    "blockquote", "pre", "figure", "figcaption", "dl", "dt", "dd", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th",
})
HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
PARA_TAGS = HEADINGS | {"p", "section", "article", "main", "blockquote", "pre", "table", "ul", "ol", "figure", "hr"}
PARA = "\n\x01\n"  # marca de quebra de parágrafo (vira linha em branco)


class WebError(Exception):
    """Erro já com mensagem pronta para o usuário."""


# SSRF ----------------------------------------------------------------------------
def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return True
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return bool(
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
        or addr.is_reserved or addr.is_unspecified
        or (isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10"))
    )


def check_url_allowed(
    url: str,
    allow_private: bool = False,
    resolver: Callable[..., Any] = socket.getaddrinfo,
) -> str:
    """Valida e normaliza a URL. Levanta WebError se não for permitida."""
    url = (url or "").strip()
    if not url:
        raise WebError("Faltou o endereço da página.")
    if "://" not in url and not url.lower().startswith(("file:", "data:", "javascript:")):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise WebError(f"Só abro endereços http ou https (recebi '{scheme or url}').")
    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise WebError("Endereço sem nome de site.")
    if allow_private:
        return url
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise WebError("Não acesso endereços da rede local ou do próprio computador.")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        raise WebError("Porta inválida no endereço.") from None
    try:
        ipaddress.ip_address(host.strip("[]"))
        literal = True
    except ValueError:
        literal = False
    if literal:
        if _ip_blocked(host.strip("[]")):
            raise WebError("Não acesso endereços da rede local ou do próprio computador.")
        return url
    try:
        infos = resolver(host, port, 0, socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise WebError(f"Não consegui encontrar o site {host}.") from None
    ips = {str(info[4][0]) for info in infos}
    if not ips or any(_ip_blocked(ip) for ip in ips):
        raise WebError("Não acesso endereços da rede local ou do próprio computador.")
    return url


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, guard: Callable[[str], str]) -> None:
        self.guard = guard

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        self.guard(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Decodificação --------------------------------------------------------------------
def _decompress(data: bytes, encoding: str, limit: int) -> bytes:
    encoding = (encoding or "").strip().lower()
    if encoding in ("", "identity"):
        return data
    if encoding in ("gzip", "x-gzip"):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decoder = zlib.decompressobj()
        try:
            out = decoder.decompress(data, limit)
            return out
        except zlib.error:
            decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    else:
        return data
    try:
        return decoder.decompress(data, limit)
    except zlib.error:
        raise WebError("A página veio compactada de um jeito que não consegui abrir.") from None


_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)


def _valid_codec(name: str | None) -> str | None:
    if not name:
        return None
    import codecs

    try:
        return codecs.lookup(name.strip().strip("\"'")).name
    except (LookupError, ValueError):
        return None


def decode_body(data: bytes, header_charset: str | None = None) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    charset = _valid_codec(header_charset)
    if charset is None:
        match = _META_CHARSET.search(data[:8192])
        if match:
            charset = _valid_codec(match.group(1).decode("ascii", errors="ignore"))
    if charset is not None:
        if charset in ("latin-1", "iso8859-1", "ascii"):
            charset = "cp1252"  # navegadores tratam latin-1 como windows-1252
        return data.decode(charset, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# Extração de texto ------------------------------------------------------------------
class _Extractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.skip = 0
        self.focus = 0  # dentro de <main>/<article>
        self.pre = 0
        self.chunks: list[str] = []
        self.focus_chunks: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.og_title = ""
        self.links: list[dict[str, str]] = []
        self._link: dict[str, Any] | None = None

    def _emit(self, text: str) -> None:
        self.chunks.append(text)
        if self.focus:
            self.focus_chunks.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
            return
        if tag == "meta":
            values = {k.lower(): (v or "") for k, v in attrs}
            if values.get("property", "").lower() == "og:title" and not self.og_title:
                self.og_title = values.get("content", "").strip()
            return
        if tag == "base":
            href = dict(attrs).get("href")
            if href:
                self.base_url = urllib.parse.urljoin(self.base_url, href)
            return
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self._link = {"href": href, "text": []}
        if tag in SKIP_TAGS:
            self.skip += 1
            return
        if tag in ("main", "article"):
            self.focus += 1
        if self.skip:
            return
        if tag == "pre":
            self.pre += 1
        if tag in BLOCK_TAGS:
            self._emit(PARA if tag in PARA_TAGS else "\n")
            if tag == "li":
                self._emit("- ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in SKIP_TAGS:
            return  # <svg/> não abre bloco
        self.handle_starttag(tag, attrs)
        if tag.lower() == "a":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
            return
        if tag == "a" and self._link is not None:
            self._finish_link()
        if tag in SKIP_TAGS:
            if self.skip:
                self.skip -= 1
            return
        if tag in ("main", "article") and self.focus:
            self.focus -= 1
        if tag == "pre" and self.pre:
            self.pre -= 1
        if not self.skip and tag in BLOCK_TAGS:
            self._emit(PARA if tag in PARA_TAGS else "\n")

    def _finish_link(self) -> None:
        link = self._link
        self._link = None
        if not link:
            return
        href = str(link["href"]).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return
        absolute = urllib.parse.urljoin(self.base_url, href)
        absolute, _ = urllib.parse.urldefrag(absolute)
        if not absolute.lower().startswith(("http://", "https://")):
            return
        text = " ".join(" ".join(link["text"]).split())
        self.links.append({"text": text[:200], "href": absolute})

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        if self._link is not None:
            self._link["text"].append(data)
        if not self.skip:
            self._emit(data if self.pre else re.sub(r"\s+", " ", data))

    def close(self) -> None:
        try:
            super().close()
        finally:
            if self._link is not None:
                self._finish_link()


def _clean_text(chunks: list[str]) -> str:
    raw = "".join(chunks)
    out: list[str] = []
    blank = False
    for line in raw.split("\n"):
        if "\x01" in line:
            blank = bool(out)
            line = line.replace("\x01", "")
        line = " ".join(line.split())
        if not line or line == "-":
            continue
        if blank and out:
            out.append("")
        out.append(line)
        blank = False
    return "\n".join(out).strip()


def extract_page(html: str, base_url: str) -> dict[str, Any]:
    parser = _Extractor(base_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass  # HTML quebrado: fica com o que deu para ler
    title = " ".join("".join(parser.title_parts).split()) or parser.og_title
    text = _clean_text(parser.chunks)
    focus = _clean_text(parser.focus_chunks)
    if len(focus) >= 200:
        text = focus
    unique: dict[str, dict[str, str]] = {}
    for link in parser.links:
        unique.setdefault(link["href"], link)
    return {"title": title, "text": text, "links": list(unique.values())}


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    space = max(cut.rfind("\n"), cut.rfind(" "))
    if space > limit * 0.8:
        cut = cut[:space]
    return cut.rstrip() + " […]", True


# Nomes de arquivo -------------------------------------------------------------------
def _content_disposition_name(header: str) -> str:
    if not header:
        return ""
    match = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", header, re.I)
    if match:
        charset = match.group(1) or "utf-8"
        try:
            return urllib.parse.unquote(match.group(2).strip().strip('"'), encoding=charset, errors="replace")
        except LookupError:
            return urllib.parse.unquote(match.group(2).strip().strip('"'))
    match = re.search(r'filename\s*=\s*"([^"]*)"', header, re.I) or re.search(r"filename\s*=\s*([^;]+)", header, re.I)
    return match.group(1).strip() if match else ""


def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f\x7f]', "_", name)
    name = " ".join(name.split()).strip(" .")
    if not name:
        return ""
    stem, ext = os.path.splitext(name)
    if stem.lower() in WINDOWS_RESERVED or not stem:
        stem = f"_{stem}" if stem else "download"
    if len(ext) > 16:
        ext = ""
    stem = stem[: 150 - len(ext)]
    return stem + ext


def is_executable_name(name: str) -> bool:
    lowered = name.lower().rstrip(" .")
    return any(lowered.endswith(ext) for ext in EXECUTABLE_EXTENSIONS)


def _unique_open(folder: Path, name: str) -> tuple[Path, Any]:
    stem, ext = os.path.splitext(name)
    for index in range(0, 1000):
        candidate = folder / (name if index == 0 else f"{stem} ({index}){ext}")
        try:
            return candidate, open(candidate, "xb")
        except FileExistsError:
            continue
    raise WebError("Já existem arquivos demais com esse nome na pasta.")


def _windows_downloads() -> Path | None:
    try:
        import ctypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
        guid = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        windll = getattr(ctypes, "windll")
        pointer = ctypes.c_wchar_p()
        result = windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer))
        value = pointer.value
        windll.ole32.CoTaskMemFree(pointer)
        if result != 0 or not value:
            return None
        return Path(value)
    except Exception:
        return None


def default_downloads_dir() -> Path:
    if IS_WINDOWS:
        found = _windows_downloads()
        if found is not None:
            return found
    return Path.home() / "Downloads"


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(value)} bytes"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{size} bytes"


def _fail(message: str, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": message, "message": message, **extra}


# Ferramentas ----------------------------------------------------------------------
class WebTools:
    def __init__(
        self,
        allow_private: bool = False,
        downloads_dir: str | Path | None = None,
        proxies: dict[str, str] | None = None,
        timeout: float = TIMEOUT,
        resolver: Callable[..., Any] = socket.getaddrinfo,
    ) -> None:
        # allow_private=True só em testes (servidor local).
        self.allow_private = allow_private
        self.downloads_dir = Path(downloads_dir) if downloads_dir else None
        self.timeout = timeout
        self.resolver = resolver
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            _GuardedRedirect(self._guard),
        )

    def _guard(self, url: str) -> str:
        return check_url_allowed(url, self.allow_private, self.resolver)

    def _open(self, url: str, method: str = "GET", headers: dict[str, str] | None = None) -> Any:
        url = self._guard(url)
        request = urllib.request.Request(url, method=method, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            **(headers or {}),
        })
        return self._opener.open(request, timeout=self.timeout)

    def _fetch_page(self, url: str) -> dict[str, Any]:
        """Baixa a página (até 3 MB). Levanta WebError com mensagem pronta."""
        try:
            response = self._open(url)
        except WebError:
            raise
        except urllib.error.HTTPError as exc:
            raise WebError(f"O site respondeu com erro {exc.code}.") from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, WebError):
                raise reason from None
            raise WebError(f"Não consegui abrir o site ({reason}).") from None
        except (TimeoutError, socket.timeout):
            raise WebError("O site demorou demais para responder.") from None
        except (OSError, ValueError) as exc:
            raise WebError(f"Não consegui abrir o site ({exc}).") from None
        with response:
            final_url = response.geturl()
            content_type = (response.headers.get_content_type() or "").lower()
            charset = response.headers.get_content_charset()
            encoding = response.headers.get("Content-Encoding", "")
            info = {"final_url": final_url, "content_type": content_type, "status": getattr(response, "status", 200)}
            if content_type == "application/pdf" or (
                content_type in ("application/octet-stream", "binary/octet-stream")
                and urllib.parse.urlsplit(final_url).path.lower().endswith(".pdf")
            ):
                return {**info, "kind": "pdf"}
            textual = content_type.startswith("text/") or content_type in (
                "", "application/xhtml+xml", "application/xml", "application/json", "application/ld+json",
            ) or content_type.endswith(("+xml", "+json"))
            if not textual:
                return {**info, "kind": "binary"}
            try:
                data = response.read(MAX_PAGE_BYTES + 1)
            except (TimeoutError, socket.timeout):
                raise WebError("O site demorou demais para responder.") from None
            except OSError as exc:
                raise WebError(f"A conexão caiu enquanto lia a página ({exc}).") from None
        cut = len(data) > MAX_PAGE_BYTES
        data = _decompress(data[:MAX_PAGE_BYTES], encoding, MAX_PAGE_BYTES * 4)
        html = decode_body(data, charset)
        return {**info, "kind": "html" if "html" in content_type or not content_type else "text", "body": html, "cut": cut}

    def read_webpage(self, url: str, max_chars: int = 12000) -> dict[str, Any]:
        try:
            max_chars = max(500, min(int(max_chars or 12000), 100_000))
        except (TypeError, ValueError):
            max_chars = 12000
        try:
            page = self._fetch_page(url)
        except WebError as exc:
            return _fail(str(exc), url=url)
        final_url = page["final_url"]
        if page["kind"] == "pdf":
            return {
                "message": "Esse endereço é um PDF, não uma página. Posso baixar com download_file.",
                "url": url, "final_url": final_url, "title": "", "text": "", "truncated": False,
                "links_count": 0, "is_pdf": True, "content_type": page["content_type"],
            }
        if page["kind"] == "binary":
            return _fail(
                f"Esse endereço não é uma página de texto ({page['content_type']}). Posso baixar com download_file.",
                url=url, final_url=final_url, content_type=page["content_type"],
            )
        if page["kind"] == "html":
            extracted = extract_page(page["body"], final_url)
        else:
            extracted = {"title": "", "text": _clean_text([page["body"]]), "links": []}
        text, truncated = truncate(extracted["text"], max_chars)
        title = extracted["title"]
        if not text:
            message = f"Abri {title or final_url}, mas não encontrei texto legível (talvez a página dependa de JavaScript)."
        else:
            message = f"Li a página {title or final_url} ({len(text)} caracteres" + (", resumida)." if truncated else ").")
        return {
            "message": message, "url": url, "final_url": final_url, "title": title, "text": text,
            "truncated": truncated or bool(page.get("cut")), "links_count": len(extracted["links"]),
        }

    def page_links(self, url: str, contains: str = "", limit: int = 30) -> dict[str, Any]:
        try:
            limit = max(1, min(int(limit or 30), 200))
        except (TypeError, ValueError):
            limit = 30
        try:
            page = self._fetch_page(url)
        except WebError as exc:
            return _fail(str(exc), url=url)
        if page["kind"] != "html":
            return _fail("Esse endereço não é uma página HTML; não há links para listar.", url=url, final_url=page["final_url"])
        links = extract_page(page["body"], page["final_url"])["links"]
        needle = (contains or "").casefold().strip()
        if needle:
            links = [link for link in links if needle in link["text"].casefold() or needle in link["href"].casefold()]
        total = len(links)
        links = links[:limit]
        if not links:
            extra = f" com '{contains}'" if needle else ""
            return {"message": f"Não encontrei links{extra} nessa página.", "url": url, "final_url": page["final_url"], "links": [], "total": 0}
        return {
            "message": f"Encontrei {total} link(s)" + (f", mostrando {len(links)}." if total > len(links) else "."),
            "url": url, "final_url": page["final_url"], "links": links, "total": total,
        }

    def check_url(self, url: str) -> dict[str, Any]:
        response = None
        try:
            try:
                response = self._open(url, method="HEAD")
            except urllib.error.HTTPError as exc:
                if exc.code not in (403, 405, 501):
                    response = exc
                else:
                    response = self._open(url, headers={"Range": "bytes=0-0"})
        except WebError as exc:
            return _fail(str(exc), url=url)
        except urllib.error.HTTPError as exc:
            response = exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            return _fail(str(reason) if isinstance(reason, WebError) else f"Não consegui acessar o endereço ({reason}).", url=url, reachable=False)
        except (OSError, ValueError) as exc:
            return _fail(f"Não consegui acessar o endereço ({exc}).", url=url, reachable=False)
        try:
            status = int(getattr(response, "status", None) or getattr(response, "code", 0) or 0)
            headers = response.headers
            final_url = response.geturl() if hasattr(response, "geturl") else url
            content_type = headers.get("Content-Type", "") if headers else ""
            size: int | None = None
            content_range = headers.get("Content-Range", "") if headers else ""
            match = re.search(r"/(\d+)\s*$", content_range or "")
            if match:
                size = int(match.group(1))
            elif headers and (headers.get("Content-Length") or "").strip().isdigit() and status != 206:
                size = int(headers["Content-Length"])
        finally:
            try:
                response.close()
            except Exception:
                pass
        ok = 200 <= status < 400
        size_text = f", {_human_size(size)}" if size is not None else ""
        message = (
            f"O endereço está no ar (código {status}{size_text})." if ok
            else f"O endereço respondeu com erro {status}."
        )
        return {
            "message": message, "url": url, "final_url": final_url, "status": status, "ok": ok,
            "reachable": True, "content_type": content_type, "size": size,
        }

    def _target_folder(self, folder: str) -> Path:
        key = (folder or "downloads").casefold().strip()
        downloads = self.downloads_dir or default_downloads_dir()
        if key in ("", "downloads", "download"):
            return downloads
        if key in FOLDER_ALIASES:
            return Path.home() / FOLDER_ALIASES[key]
        path = Path(folder).expanduser()
        return path if path.is_absolute() else downloads / path

    def download_file(self, url: str, folder: str = "downloads", name: str = "") -> dict[str, Any]:
        target_dir = self._target_folder(folder)
        requested = sanitize_filename(name) if name else ""
        if requested and is_executable_name(requested):
            return _fail("Não baixo programas ou scripts executáveis por aqui; se precisar, baixe pelo navegador.", url=url)
        try:
            response = self._open(url, headers={"Accept": "*/*", "Accept-Encoding": "identity"})
        except WebError as exc:
            return _fail(str(exc), url=url)
        except urllib.error.HTTPError as exc:
            return _fail(f"O site respondeu com erro {exc.code}.", url=url)
        except urllib.error.URLError as exc:
            reason = exc.reason
            return _fail(str(reason) if isinstance(reason, WebError) else f"Não consegui baixar ({reason}).", url=url)
        except (OSError, ValueError) as exc:
            return _fail(f"Não consegui baixar ({exc}).", url=url)
        path: Path | None = None
        with response:
            final_url = response.geturl()
            content_type = (response.headers.get_content_type() or "").lower()
            length_header = (response.headers.get("Content-Length") or "").strip()
            if length_header.isdigit() and int(length_header) > MAX_DOWNLOAD_BYTES:
                return _fail(f"O arquivo tem {_human_size(int(length_header))}; o limite é 500 MB.", url=url)
            server_name = _content_disposition_name(response.headers.get("Content-Disposition", ""))
            url_name = urllib.parse.unquote(urllib.parse.urlsplit(final_url).path.rsplit("/", 1)[-1])
            candidates = [requested, sanitize_filename(server_name), sanitize_filename(url_name)]
            if any(c and is_executable_name(c) for c in candidates[1:]) and not requested:
                return _fail("Não baixo programas ou scripts executáveis por aqui; se precisar, baixe pelo navegador.", url=url)
            filename = next((c for c in candidates if c), "") or "download"
            if not os.path.splitext(filename)[1] and content_type not in ("", "application/octet-stream"):
                guessed = mimetypes.guess_extension(content_type) or ""
                if guessed in (".htm", ".shtml"):
                    guessed = ".html"
                filename += guessed
            if is_executable_name(filename) or content_type in (
                "application/x-msdownload", "application/x-msdos-program", "application/x-ms-installer",
            ):
                return _fail("Não baixo programas ou scripts executáveis por aqui; se precisar, baixe pelo navegador.", url=url)
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                path, handle = _unique_open(target_dir, filename)
            except WebError as exc:
                return _fail(str(exc), url=url)
            except OSError as exc:
                return _fail(f"Não consegui criar o arquivo em {target_dir} ({exc}).", url=url)
            size = 0
            deadline = time.monotonic() + DOWNLOAD_DEADLINE
            error = ""
            try:
                with handle:
                    while True:
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            error = "O arquivo passou de 500 MB; cancelei o download."
                            break
                        if time.monotonic() > deadline:
                            error = "O download demorou demais; cancelei."
                            break
                        handle.write(chunk)
            except (TimeoutError, socket.timeout):
                error = "O site parou de responder no meio do download."
            except OSError as exc:
                error = f"O download falhou ({exc})."
            if length_header.isdigit() and not error and size < int(length_header):
                error = "O download veio incompleto."
            if error:
                try:
                    path.unlink()
                except OSError:
                    pass
                return _fail(error, url=url)
        return {
            "message": f"Baixei {path.name} ({_human_size(size)}) em {target_dir}.",
            "url": url, "final_url": final_url, "path": str(path), "name": path.name,
            "size": size, "content_type": content_type,
        }

    # registro ------------------------------------------------------------------
    SPECS: list[tuple[str, str, tuple[str, ...], dict[str, Any]]] = [
        ("read_webpage", "Lê o texto de uma página da web (notícia, artigo, site) para resumir ou responder sobre ela", ("url",), {"url": str, "max_chars": int}),
        ("page_links", "Lista os links de uma página da web, opcionalmente filtrando por um texto", ("url",), {"url": str, "contains": str, "limit": int}),
        ("download_file", "Baixa um arquivo (PDF, imagem, documento...) da internet para a pasta Downloads", ("url",), {"url": str, "folder": str, "name": str}),
        ("check_url", "Verifica se um endereço da web está no ar: código, tipo e tamanho", ("url",), {"url": str}),
    ]

    RISK: dict[str, str] = {
        "read_webpage": "low",
        "page_links": "low",
        "download_file": "medium",
        "check_url": "low",
    }

    def register(self, executor: Any, schemas: Any | None = None) -> None:
        from brain.tool_schema import ToolSpec

        for name, description, required, types in self.SPECS:
            executor.register(name, getattr(self, name))
            if schemas is not None:
                schemas.register(ToolSpec(name, description, required, types))
