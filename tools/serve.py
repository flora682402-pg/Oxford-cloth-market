"""Local server that behaves like Cloudflare Pages for testing.

    python3 tools/serve.py [dist] [port]

- clean URLs: /clothing serves clothing.html, /clothing.html redirects to /clothing
- unknown paths serve 404.html with status 404
- applies the response headers from dist/_headers (CSP, caching, ...)
"""
from __future__ import annotations

import fnmatch
import http.server
import sys
import threading
from pathlib import Path


def parse_headers(path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    rules, current = [], None
    if not path.exists():
        return rules
    for raw in path.read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t")):
            current = (raw.strip(), [])
            rules.append(current)
        elif current is not None:
            name, _, value = raw.strip().partition(":")
            current[1].append((name.strip(), value.strip()))
    return rules


def make_handler(root: Path):
    rules = parse_headers(root / "_headers")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *args):  # keep test output quiet
            pass

        def end_headers(self):
            path = self.path.split("?", 1)[0].split("#", 1)[0]
            for pattern, headers in rules:
                if fnmatch.fnmatch(path, pattern):
                    for k, v in headers:
                        self.send_header(k, v)
            super().end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path.endswith(".html") and path != "/404.html":
                target = "/" if path == "/index.html" else path[:-5]
                self.send_response(308)
                self.send_header("Location", target)
                self.end_headers()
                return
            fs = root / path.lstrip("/")
            if path != "/" and not fs.exists() and (root / (path.lstrip("/") + ".html")).is_file():
                self.path = path + ".html"
            elif path != "/" and not fs.exists():
                body = (root / "404.html").read_bytes()
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    return Handler


def start(root: Path, port: int = 0) -> http.server.ThreadingHTTPServer:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "dist").resolve()
    srv = start(root, int(sys.argv[2]) if len(sys.argv) > 2 else 8000)
    print(f"Serving {root} at http://127.0.0.1:{srv.server_address[1]}/  (Ctrl+C to stop)")
    threading.Event().wait()
