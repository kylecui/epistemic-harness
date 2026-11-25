"""router-gate: one stable port in front of two interchangeable backends.

Both backends run the same image; only one is active. Upgrading means starting the idle side,
health-checking it, and flipping the gate — so the client (pi, pinned to 8787) never sees a
refused connection during an upgrade, which is what happened on 2026-11-25 when a bad image
looped in `Restarting` and every turn died with ECONNREFUSED.

Env:
  HARNESS_GATE_LISTEN   host:port to bind (default 0.0.0.0:8787)
  HARNESS_GATE_BACKENDS blue=http://backend-blue:8787,green=http://backend-green:8787
  HARNESS_GATE_ACTIVE   initial active backend name (default: first listed)
"""
from __future__ import annotations

import http.client
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = os.environ.get("HARNESS_GATE_LISTEN", "0.0.0.0:8787")


def parse_backends(spec: str) -> list[tuple[str, urllib.parse.SplitResult]]:
    out: list[tuple[str, urllib.parse.SplitResult]] = []
    for item in (spec or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, url = item.split("=", 1)
        out.append((name.strip(), urllib.parse.urlsplit(url.strip())))
    return out


BACKENDS = parse_backends(os.environ.get(
    "HARNESS_GATE_BACKENDS", "blue=http://127.0.0.1:8789,green=http://127.0.0.1:8790"))
STATE = {
    "active": os.environ.get("HARNESS_GATE_ACTIVE") or (BACKENDS[0][0] if BACKENDS else ""),
    "healthy": {name: False for name, _ in BACKENDS},
    "flips": [],
}
LOCK = threading.Lock()


def backend_url(name: str) -> urllib.parse.SplitResult | None:
    for bname, url in BACKENDS:
        if bname == name:
            return url
    return None


def pick_targets() -> list[str]:
    """Active first, then any other HEALTHY backend: one retry, no guessing."""
    with LOCK:
        active = STATE["active"]
        others = [n for n, _ in BACKENDS if n != active and STATE["healthy"].get(n)]
    return [active, *others]


def probe_once(name: str, timeout: float = 1.5) -> bool:
    url = backend_url(name)
    if url is None:
        return False
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=timeout)
    try:
        conn.request("GET", "/health")
        return conn.getresponse().status == 200
    except OSError:
        return False
    finally:
        conn.close()


def health_loop(interval: float = 2.0) -> None:
    while True:
        for name, _ in BACKENDS:
            ok = probe_once(name)
            with LOCK:
                STATE["healthy"][name] = ok
        time.sleep(interval)


class Gate(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self) -> None:
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            # A client closing a keep-alive socket is normal traffic, not a traceback.
            self.close_connection = True

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib signature
        if os.environ.get("HARNESS_GATE_VERBOSE"):
            print(f"gate: {fmt % args}", flush=True)

    def _admin(self) -> bool:
        parsed = urllib.parse.urlsplit(self.path)
        if not parsed.path.startswith("/__gate"):
            return False
        if parsed.path == "/__gate/status":
            with LOCK:
                body = json.dumps(STATE, ensure_ascii=False).encode()
        else:
            target = urllib.parse.parse_qs(parsed.query).get("active", [""])[0]
            if backend_url(target) is None:
                self.send_response(404)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", "0")
                self.end_headers()
                return True
            with LOCK:
                STATE["active"] = target
                STATE["flips"].append({"to": target, "ts": time.time()})
                body = json.dumps({"ok": True, "active": target}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _forward(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        payload = self.rfile.read(length) if length else None
        last_error: OSError | None = None
        for name in pick_targets():
            url = backend_url(name)
            if url is None:
                continue
            conn = http.client.HTTPConnection(url.hostname, url.port, timeout=600)
            try:
                headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in ("host", "connection")}
                conn.request(self.command, self.path, body=payload, headers=headers)
                resp = conn.getresponse()
                self.send_response(resp.status)
                for key, value in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection", "content-length"):
                        self.send_header(key, value)
                self.send_header("x-harness-gate-backend", name)
                self.send_header("connection", "close")
                self.end_headers()
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                self.close_connection = True
                with LOCK:
                    if STATE["active"] != name:
                        # A transparent retry that succeeded is also a liveness verdict: remember it,
                        # so the next request does not pay for the dead side again.
                        STATE["flips"].append({"to": name, "ts": time.time(), "auto": True})
                        STATE["active"] = name
                return
            except OSError as exc:  # connect refused / reset: the request never reached an upstream
                last_error = exc
                continue
            finally:
                conn.close()
        body = json.dumps({"error": {"type": "gate_no_backend", "message": str(last_error)}}).encode()
        self.send_response(502)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if not self._admin():
            self._forward()

    def do_POST(self) -> None:  # noqa: N802
        if not self._admin():
            self._forward()

    def do_PUT(self) -> None:  # noqa: N802
        self._forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward()


def main() -> int:
    host, _, port = LISTEN.rpartition(":")
    threading.Thread(target=health_loop, daemon=True).start()
    server = ThreadingHTTPServer((host or "0.0.0.0", int(port or 8787)), Gate)
    print(f"router-gate on {LISTEN}, backends={[n for n, _ in BACKENDS]}, active={STATE['active']}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
