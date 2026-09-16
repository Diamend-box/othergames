"""A small local HTTP server for the planner UI.

The standard library is enough for a single-user tool on localhost, and
keeping it dependency-free means the packaged executable stays small and the
build has nothing to resolve.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import Settings
from ..savegame.discovery import SaveWatcher
from ..service import PlannerService

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 8 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    service: PlannerService  # injected by make_server
    server_version = "satplanner"

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: object, status: int = 200) -> None:
        self._send(status, json.dumps(payload, default=str).encode("utf-8"), "application/json")

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > MAX_BODY_BYTES:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _static(self, name: str) -> None:
        # Resolve inside STATIC_DIR so a crafted path cannot escape it.
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self._send(404, b"Not found", "text/plain")
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), content_type)

    # -- routes ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        url = urlparse(self.path)
        route = url.path.rstrip("/") or "/"
        query = parse_qs(url.query)
        service = self.service

        if route == "/":
            self._static("index.html")
        elif route.startswith("/static/"):
            self._static(route[len("/static/") :])
        elif route == "/api/status":
            self._json(service.status())
        elif route == "/api/saves":
            self._json({"ok": True, "saves": service.saves()})
        elif route == "/api/plan":
            self._json({"ok": True, "plan": service.plan.to_dict()})
        elif route == "/api/report":
            self._json(service.report())
        elif route == "/api/grid":
            self._json(service.grid())
        elif route == "/api/modeler/scan":
            directory = query.get("dir", [None])[0]
            self._json(service.scan_modeler(directory))
        else:
            self._json({"ok": False, "error": f"Unknown route {route}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        route = urlparse(self.path).path.rstrip("/") or "/"
        body = self._body()
        service = self.service

        if route == "/api/refresh":
            self._json(service.refresh(force=bool(body.get("force", True))))
        elif route == "/api/select-save":
            self._json(service.select_save(str(body.get("path", ""))))
        elif route == "/api/plan":
            self._json(service.set_plan(body.get("plan", body)))
        elif route == "/api/modeler/import":
            self._json(service.import_modeler(str(body.get("path", ""))))
        else:
            self._json({"ok": False, "error": f"Unknown route {route}"}, status=404)

    do_PUT = do_POST


def make_server(service: PlannerService, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"service": service})
    return ThreadingHTTPServer((host, port), handler)


def serve(settings: Settings | None = None, open_browser: bool = True) -> None:
    """Start the UI and block until interrupted."""
    settings = settings or Settings()
    service = PlannerService(settings)

    # A first parse up front means the page has something to show immediately.
    service.refresh()

    watcher = SaveWatcher(
        get_path=service.current_save_path,
        on_change=lambda _path: service.refresh(force=True),
        interval=float(settings.poll_seconds),
    )
    watcher.start()

    httpd = make_server(service, settings.host, settings.port)
    url = f"http://{settings.host}:{settings.port}/"
    print(f"Satisfactory planner running at {url}")
    print("Leave this window open. Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        watcher.stop()
        httpd.server_close()
