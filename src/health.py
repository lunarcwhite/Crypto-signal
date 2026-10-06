"""Health endpoint stdlib (PRD §5 observabilitas) + multi-instance guard.

Port yang di-bind berfungsi ganda: bila port sudah dipakai, diasumsikan
instance lain berjalan -> caller harus exit (mencegah 2 writer ke SQLite sama).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _port_in_use(port: int) -> bool:
    import socket

    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_health_server(port: int, provider) -> ThreadingHTTPServer:
    """provider() -> dict status. Raise OSError bila port terpakai (=guard).

    Guard via connect-test eksplisit (bukan andalkan SO_REUSE), agar dua
    instance tidak bisa hidup berdampingan di port yang sama.
    """

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_response(404)
                self.end_headers()
                return
            try:
                body = json.dumps({"status": "ok", **provider()}).encode()
            except Exception as e:  # noqa: BLE001
                body = json.dumps({"status": "error", "detail": str(e)[:200]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    if port != 0 and _port_in_use(port):
        raise OSError(f"port {port} sudah dipakai — kemungkinan instance lain berjalan")
    srv = ThreadingHTTPServer(("127.0.0.1", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
