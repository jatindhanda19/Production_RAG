"""Dev server for the frontend: serves the static files and proxies /api/* to the API.

The API has no CORS middleware, so the browser has to reach it same-origin.

    python frontend/serve.py                  # http://localhost:5173 -> http://localhost:8000

Override with the API_URL and PORT environment variables.
"""

import json
import os
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
PORT = int(os.environ.get("PORT", "5173"))
STATIC_DIR = Path(__file__).parent

# The agent may try the primary and then the fallback model, 30s timeout each
PROXY_TIMEOUT = 120


class Handler(SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._proxy()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy()
        else:
            self.send_error(405)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        request = urllib.request.Request(
            API_URL + self.path[len("/api"):],
            data=body,
            method=self.command,
        )
        content_type = self.headers.get("Content-Type")
        if content_type:
            request.add_header("Content-Type", content_type)

        try:
            with urllib.request.urlopen(request, timeout=PROXY_TIMEOUT) as upstream:
                status, headers, payload = upstream.status, upstream.headers, upstream.read()
        except urllib.error.HTTPError as e:
            # 4xx/5xx from the API: pass it through unchanged
            status, headers, payload = e.code, e.headers, e.read()
        except (urllib.error.URLError, OSError) as e:
            status, headers = 502, {}
            payload = json.dumps({
                "error": "api_unreachable",
                "detail": f"Could not reach the API at {API_URL}: {e}",
            }).encode()

        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(payload)))
        if headers.get("Retry-After"):
            self.send_header("Retry-After", headers["Retry-After"])
        try:
            self.end_headers()
            self.wfile.write(payload)
        except ConnectionError:
            # The browser gave up (tab closed or reloaded) before the reply was ready
            pass


if __name__ == "__main__":
    handler = partial(Handler, directory=str(STATIC_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    print(f"Frontend: http://localhost:{PORT}  ->  API: {API_URL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
