"""Local test website with deliberate SEO problems.

Used by the pytest fixtures and runnable directly for manual audits:

    python tests/serve_site.py 8765
    seoforge audit http://127.0.0.1:8765
"""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE_DIR = Path(__file__).parent / "site"

SOFT_404 = b"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Page not found</title></head><body><h1>Page not found</h1>
<p>Sorry, we could not find that page.</p></body></html>"""

INDEXNOW_KEY = "seoforgetestkey1234"

REDIRECTS = {
    "/old-page": (301, "/old-page-2"),
    "/old-page-2": (302, "/about"),
    "/loop-a": (301, "/loop-b"),
    "/loop-b": (301, "/loop-a"),
}


def _resolve(path: str) -> Path | None:
    clean = path.split("?", 1)[0]
    candidates = [clean.lstrip("/")]
    if clean.endswith("/"):
        candidates.append(clean.lstrip("/") + "index.html")
    else:
        candidates.append(clean.lstrip("/") + ".html")
    for c in candidates:
        f = (SITE_DIR / c).resolve()
        if f.is_file() and SITE_DIR.resolve() in f.parents:
            return f
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "TestSite/1.0"

    def log_message(self, *args: object) -> None:  # silence
        pass

    def _send(
        self,
        status: int,
        body: bytes,
        ctype: str = "text/html; charset=utf-8",
        extra: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        base = f"http://{self.headers.get('Host')}"
        path = self.path.split("#", 1)[0]
        if path in REDIRECTS:
            status, target = REDIRECTS[path]
            self.send_response(status)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == f"/{INDEXNOW_KEY}.txt":
            self._send(200, INDEXNOW_KEY.encode(), "text/plain; charset=utf-8")
            return
        if path == "/broken-page":
            self._send(404, b"<html><title>404</title><body>Not found</body></html>")
            return
        if path == "/server-error":
            self._send(500, b"error")
            return
        f = _resolve(path)
        if f is None:
            # Deliberate soft 404: unknown URLs return 200.
            self._send(200, SOFT_404)
            return
        alt = f"localhost:{self.server.server_address[1]}"
        body = f.read_bytes().replace(b"{{BASE}}", base.encode()).replace(b"{{ALT}}", alt.encode())
        ctype = {
            ".txt": "text/plain; charset=utf-8",
            ".xml": "application/xml",
        }.get(f.suffix, "text/html; charset=utf-8")
        extra = {}
        if f.name == "contact.html":
            extra["X-Robots-Tag"] = "nosnippet"
        self._send(200, body, ctype, extra)


def start(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    srv, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
    print(f"Serving test site at {url}  (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
