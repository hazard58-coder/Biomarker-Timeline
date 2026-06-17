"""Minimal static server for the Biomarker Timeline landing page.

Used to host landing.html on Railway. Standard library only — no web framework,
in keeping with the rest of the project. Serves:

  /            -> landing.html
  /sample.pdf  -> the finished sample report (so prospects can see a real one)

Railway sets the PORT environment variable; we bind to it.
"""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LANDING = ROOT / "landing.html"
SAMPLE = ROOT / "samples" / "Marcus_Hale_Biomarker_Timeline_SAMPLE.pdf"

ROUTES = {
    "/": (LANDING, "text/html; charset=utf-8"),
    "/index.html": (LANDING, "text/html; charset=utf-8"),
    "/sample.pdf": (SAMPLE, "application/pdf"),
    "/healthz": (None, "text/plain; charset=utf-8"),  # Railway healthcheck
}


class Handler(BaseHTTPRequestHandler):
    server_version = "VitalisForgeStatic/1.0"

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send(200, b"ok", "text/plain; charset=utf-8")
            return
        route = ROUTES.get(path)
        if route is None:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        file_path, content_type = route
        if file_path is None or not file_path.exists():
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        self._send(200, file_path.read_bytes(), content_type)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving Biomarker Timeline landing page on 0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
