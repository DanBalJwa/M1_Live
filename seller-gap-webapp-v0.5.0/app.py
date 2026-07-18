from __future__ import annotations

import json
import mimetypes
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from core import (
    analyze_category,
    analyze_keyword,
    analyze_uploaded_coupang_html,
    ensure_data,
    load_categories,
    load_config,
    public_config,
    save_config,
    test_connections,
)

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
HOST = "127.0.0.1"
PORT = 8000
MAX_BODY_BYTES = 12 * 1024 * 1024


class AppHandler(BaseHTTPRequestHandler):
    server_version = "SellerGap/0.5.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", f"http://{HOST}:{PORT}")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise RuntimeError("잘못된 Content-Length입니다.") from exc
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise RuntimeError("요청 데이터가 너무 큽니다. HTML은 12MB 이하만 지원합니다.")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("요청 JSON 형식이 올바르지 않습니다.") from exc
        if not isinstance(value, dict):
            raise RuntimeError("요청 본문은 JSON 객체여야 합니다.")
        return value

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", f"http://{HOST}:{PORT}")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self.send_json(200, {"ok": True, "version": "0.5.0"})
            return
        if path == "/api/settings":
            self.send_json(200, public_config(load_config()))
            return
        if path == "/api/categories":
            self.send_json(200, load_categories())
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            payload = self.read_json()
            if path == "/api/settings":
                self.send_json(200, save_config(payload))
                return
            if path == "/api/test-connections":
                self.send_json(200, test_connections(payload))
                return
            if path == "/api/category-analysis":
                self.send_json(200, analyze_category(payload))
                return
            if path == "/api/keyword-analysis":
                self.send_json(200, analyze_keyword(payload))
                return
            if path == "/api/coupang-html-analysis":
                self.send_json(200, analyze_uploaded_coupang_html(payload))
                return
            self.send_json(404, {"error": "API 경로를 찾을 수 없습니다."})
        except RuntimeError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": f"서버 오류: {exc}"})

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (WEB_DIR / relative).resolve()
        try:
            candidate.relative_to(WEB_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not candidate.exists() or not candidate.is_file():
            self.send_error(404)
            return
        body = candidate.read_bytes()
        mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix in {".html", ".css", ".js", ".json"}:
            mime_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}")


def main() -> None:
    ensure_data()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print("=" * 64)
    print("Seller Gap Sourcing v0.5.0")
    print(f"Open: http://{HOST}:{PORT}")
    print("Close this window or press Ctrl+C to stop.")
    print("=" * 64)
    threading.Timer(0.8, open_browser).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
