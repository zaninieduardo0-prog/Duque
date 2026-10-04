from __future__ import annotations

import gzip
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from computer.web_tools import WebTools, check_url_allowed, sanitize_filename, WebError

PAGE = """<!doctype html><html><head><title>  Notícia   do Dia </title>
<script>var segredo = "NAO_APARECE";</script><style>.x{color:red}</style></head>
<body><nav><a href="/menu">Menu topo</a> NAV_TEXTO</nav>
<header>CABECALHO</header>
<h1>Chuva forte em São Paulo</h1>
<p>A cidade teve   muita
chuva hoje.</p>
<ul><li>Item um</li><li>Item dois</li></ul>
<p><a href="materia/2.html#topo">Leia mais</a> e <a href="https://exemplo.com/x">fonte</a>
<a href="javascript:void(0)">js</a> <a href="mailto:a@b.c">mail</a></p>
<aside>LATERAL</aside><form>FORMULARIO</form><footer>RODAPE</footer>
<noscript>SEM_JS</noscript><svg><text>SVG_TEXTO</text></svg>
</body></html>"""

LATIN = "<html><head><meta charset='iso-8859-1'><title>Ação</title></head><body><p>Coração e pão</p></body></html>"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silencia
        pass

    def _send(self, body: bytes, ctype: str, extra: dict[str, str] | None = None, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        if self.path == "/nohead":
            self._send(b"", "text/plain", code=405)
        else:
            self.do_GET()

    def do_GET(self) -> None:
        path = self.path
        if path.startswith("/page"):
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/long":
            body = "<html><body>" + "".join(f"<p>Parágrafo {i} com bastante texto aqui.</p>" for i in range(500)) + "</body></html>"
            self._send(body.encode("utf-8"), "text/html")
        elif path == "/latin":
            self._send(LATIN.encode("latin-1"), "text/html")
        elif path == "/gzip":
            self._send(gzip.compress(PAGE.encode("utf-8")), "text/html; charset=utf-8", {"Content-Encoding": "gzip"})
        elif path == "/redirect":
            self._send(b"", "text/html", {"Location": "/page"}, code=302)
        elif path == "/doc.pdf":
            self._send(b"%PDF-1.4 fake", "application/pdf")
        elif path == "/arquivo":
            self._send(b"conteudo", "application/octet-stream", {"Content-Disposition": 'attachment; filename="relatório final.txt"'})
        elif path == "/files/foto.png":
            self._send(b"\x89PNG data", "image/png")
        elif path == "/setup.exe":
            self._send(b"MZ", "application/octet-stream")
        elif path == "/disfarce":
            self._send(b"MZ", "application/octet-stream", {"Content-Disposition": "attachment; filename=virus.bat"})
        elif path == "/nohead":
            self._send(b"abc", "text/plain", {"Content-Range": "bytes 0-0/1234"}, code=206)
        elif path == "/json":
            self._send(json.dumps({"a": 1}).encode(), "application/json")
        else:
            self._send(b"nao achei", "text/plain", code=404)


class WebToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.tools = WebTools(allow_private=True, downloads_dir=self.tmp, proxies={}, timeout=5)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_read_extracts_text_and_drops_noise(self) -> None:
        result = self.tools.read_webpage(self.base + "/page")
        self.assertNotIn("success", result)
        self.assertEqual(result["title"], "Notícia do Dia")
        text = result["text"]
        self.assertIn("Chuva forte em São Paulo", text)
        self.assertIn("A cidade teve muita chuva hoje.", text)
        self.assertIn("- Item um", text)
        for noise in ("NAO_APARECE", "color:red", "NAV_TEXTO", "CABECALHO", "LATERAL", "FORMULARIO", "RODAPE", "SEM_JS", "SVG_TEXTO"):
            self.assertNotIn(noise, text)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["links_count"], 3)
        json.dumps(result)

    def test_truncation(self) -> None:
        result = self.tools.read_webpage(self.base + "/long", max_chars=1000)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["text"]), 1010)

    def test_latin1_meta_charset(self) -> None:
        result = self.tools.read_webpage(self.base + "/latin")
        self.assertEqual(result["title"], "Ação")
        self.assertIn("Coração e pão", result["text"])

    def test_gzip_and_redirect(self) -> None:
        self.assertIn("Chuva forte", self.tools.read_webpage(self.base + "/gzip")["text"])
        result = self.tools.read_webpage(self.base + "/redirect")
        self.assertTrue(result["final_url"].endswith("/page"))
        self.assertIn("Chuva forte", result["text"])

    def test_pdf_and_errors(self) -> None:
        result = self.tools.read_webpage(self.base + "/doc.pdf")
        self.assertTrue(result["is_pdf"])
        self.assertIn("download_file", result["message"])
        missing = self.tools.read_webpage(self.base + "/naoexiste")
        self.assertFalse(missing["success"])
        self.assertIn("404", missing["message"])
        self.assertIn('"a": 1', self.tools.read_webpage(self.base + "/json")["text"])

    def test_links_absolute_and_filtered(self) -> None:
        result = self.tools.page_links(self.base + "/page/")
        hrefs = [link["href"] for link in result["links"]]
        self.assertIn(self.base + "/menu", hrefs)
        self.assertIn(self.base + "/page/materia/2.html", hrefs)
        self.assertIn("https://exemplo.com/x", hrefs)
        self.assertFalse(any(h.startswith(("javascript:", "mailto:")) for h in hrefs))
        filtered = self.tools.page_links(self.base + "/page", contains="leia")
        self.assertEqual([link["text"] for link in filtered["links"]], ["Leia mais"])
        self.assertEqual(len(self.tools.page_links(self.base + "/page", limit=1)["links"]), 1)

    def test_download_naming_and_no_overwrite(self) -> None:
        first = self.tools.download_file(self.base + "/arquivo")
        self.assertEqual(first["name"], "relatório final.txt")
        self.assertEqual(Path(first["path"]).read_bytes(), b"conteudo")
        self.assertEqual(Path(first["path"]).parent, self.tmp)
        second = self.tools.download_file(self.base + "/arquivo")
        self.assertEqual(second["name"], "relatório final (1).txt")
        self.assertEqual(first["size"], 8)
        png = self.tools.download_file(self.base + "/files/foto.png", folder=str(self.tmp / "sub"))
        self.assertEqual(Path(png["path"]), self.tmp / "sub" / "foto.png")
        named = self.tools.download_file(self.base + "/files/foto.png", name="../../evil:x.png")
        self.assertEqual(Path(named["path"]).parent, self.tmp)
        self.assertEqual(named["name"], "evil_x.png")

    def test_download_refuses_executables(self) -> None:
        for path, name in (("/setup.exe", ""), ("/disfarce", ""), ("/files/foto.png", "foto.ps1")):
            with self.subTest(path=path):
                result = self.tools.download_file(self.base + path, name=name)
                self.assertFalse(result["success"])
                self.assertIn("executáveis", result["message"])
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_check_url(self) -> None:
        ok = self.tools.check_url(self.base + "/page")
        self.assertEqual(ok["status"], 200)
        self.assertTrue(ok["ok"])
        self.assertIn("text/html", ok["content_type"])
        self.assertGreater(ok["size"], 100)
        fallback = self.tools.check_url(self.base + "/nohead")
        self.assertEqual(fallback["size"], 1234)
        missing = self.tools.check_url(self.base + "/x")
        self.assertEqual(missing["status"], 404)
        self.assertFalse(missing["ok"])

    def test_ssrf_guard(self) -> None:
        guarded = WebTools(downloads_dir=self.tmp, proxies={})
        for url in (self.base + "/page", "http://localhost/", "http://10.1.2.3/", "http://192.168.0.1/x",
                    "http://169.254.169.254/latest", "http://[::1]/", "http://0.0.0.0/"):
            with self.subTest(url=url):
                for result in (guarded.read_webpage(url), guarded.page_links(url), guarded.check_url(url), guarded.download_file(url)):
                    self.assertFalse(result["success"])
                    self.assertIn("rede local", result["message"])
        for url in ("file:///etc/passwd", "ftp://x.com/a"):
            self.assertFalse(guarded.read_webpage(url)["success"])
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_ssrf_guard_checks_resolved_ip(self) -> None:
        def fake_resolver(host, port, *args):
            return [(2, 1, 6, "", ("10.0.0.5", port))]

        with self.assertRaises(WebError):
            check_url_allowed("https://inocente.com/", resolver=fake_resolver)

        def public_resolver(host, port, *args):
            return [(2, 1, 6, "", ("93.184.216.34", port))]

        self.assertEqual(check_url_allowed("exemplo.com/a", resolver=public_resolver), "https://exemplo.com/a")

    def test_redirect_to_private_is_blocked(self) -> None:
        calls: list[str] = []

        def resolver(host, port, *args):
            calls.append(host)
            return [(2, 1, 6, "", ("93.184.216.34", port))]

        tools = WebTools(proxies={}, resolver=resolver)
        handlers = [h for h in getattr(tools._opener, "handlers") if h.__class__.__name__ == "_GuardedRedirect"]
        self.assertEqual(len(handlers), 1)
        with self.assertRaises(WebError):
            handlers[0].redirect_request(None, None, 302, "", {}, "http://127.0.0.1/admin")
        tools._guard("https://publico.com/")
        self.assertEqual(calls, ["publico.com"])

    def test_sanitize_and_specs(self) -> None:
        self.assertEqual(sanitize_filename("CON.txt"), "_CON.txt")
        self.assertEqual(sanitize_filename('a<b>c?.pdf'), "a_b_c_.pdf")
        self.assertEqual(sanitize_filename(" .. "), "")
        names = {spec[0] for spec in WebTools.SPECS}
        self.assertEqual(names, set(WebTools.RISK))
        for name in names:
            self.assertTrue(callable(getattr(self.tools, name)))

        class Executor:
            def __init__(self) -> None:
                self.tools: dict[str, object] = {}

            def register(self, name: str, fn: object) -> None:
                self.tools[name] = fn

        executor = Executor()
        self.tools.register(executor)
        self.assertEqual(set(executor.tools), names)


if __name__ == "__main__":
    unittest.main()
