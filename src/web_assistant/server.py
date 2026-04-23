from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .task3_service import InteractiveTask3Service


BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebAssistantHandler(BaseHTTPRequestHandler):
    service: InteractiveTask3Service

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html")
            return
        if path.startswith("/static/"):
            rel = unquote(path.removeprefix("/static/"))
            self._send_file((STATIC_DIR / rel).resolve(), root=STATIC_DIR.resolve())
            return
        if path.startswith("/generated/"):
            name = Path(unquote(path.removeprefix("/generated/"))).name
            self._send_file(self.service.result_dir / name, root=self.service.result_dir)
            return
        if path == "/api/question-bank":
            self._send_json({"items": self.service.question_bank()})
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/ask":
            self._handle_ask()
            return
        if parsed.path == "/api/reset":
            self._handle_reset()
            return
        if parsed.path == "/api/cancel":
            self._handle_cancel()
            return
        if parsed.path == "/api/heartbeat":
            self._handle_heartbeat()
            return
        if parsed.path == "/api/shutdown":
            self._handle_shutdown()
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        print("[web-assistant] " + format % args)

    def _handle_ask(self) -> None:
        try:
            payload = self._read_json()
            session_id = str(payload.get("session_id") or uuid.uuid4().hex)
            question = str(payload.get("question") or "")
            result = self.service.ask(session_id=session_id, question=question)
            self._send_json(result)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_reset(self) -> None:
        try:
            payload = self._read_json()
            session_id = str(payload.get("session_id") or uuid.uuid4().hex)
            self._send_json(self.service.reset(session_id=session_id))
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_cancel(self) -> None:
        try:
            payload = self._read_json()
            session_id = str(payload.get("session_id") or "")
            self._send_json(self.service.cancel(session_id=session_id))
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_heartbeat(self) -> None:
        if hasattr(self.server, "touch_heartbeat"):
            self.server.touch_heartbeat()  # type: ignore[attr-defined]
        self._send_json({"status": "alive"})

    def _handle_shutdown(self) -> None:
        self._send_json({"status": "shutdown"})
        threading.Thread(target=self._cleanup_and_shutdown, daemon=True).start()

    def _cleanup_and_shutdown(self) -> None:
        cleanup_server_outputs(self.server)
        self.server.shutdown()

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, root: Path | None = None) -> None:
        try:
            resolved = path.resolve()
            if root is not None and root.resolve() not in resolved.parents and resolved != root.resolve():
                self._send_json({"error": "forbidden"}, status=HTTPStatus.FORBIDDEN)
                return
            if not resolved.exists() or not resolved.is_file():
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            data = resolved.read_bytes()
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)


def build_server(host: str, port: int, service: InteractiveTask3Service) -> ThreadingHTTPServer:
    class Handler(WebAssistantHandler):
        pass

    Handler.service = service
    server = ThreadingHTTPServer((host, port), Handler)
    server.cleanup_web_outputs = service.cleanup_outputs  # type: ignore[attr-defined]
    server.web_outputs_cleaned = False  # type: ignore[attr-defined]
    return server


def cleanup_server_outputs(server: ThreadingHTTPServer) -> None:
    if getattr(server, "web_outputs_cleaned", False):
        return
    server.web_outputs_cleaned = True  # type: ignore[attr-defined]
    if hasattr(server, "cleanup_web_outputs"):
        try:
            result = server.cleanup_web_outputs()  # type: ignore[attr-defined]
            print(f"网页输出清理结果: {result}", flush=True)
        except Exception as exc:
            print(f"网页输出清理失败: {exc}", flush=True)


def start_heartbeat_monitor(server: ThreadingHTTPServer, timeout_seconds: float = 18.0) -> None:
    import time

    server.last_heartbeat_monotonic = time.monotonic()  # type: ignore[attr-defined]

    def touch_heartbeat() -> None:
        server.last_heartbeat_monotonic = time.monotonic()  # type: ignore[attr-defined]

    def monitor() -> None:
        while True:
            time.sleep(3.0)
            last_seen = float(getattr(server, "last_heartbeat_monotonic", time.monotonic()))
            if time.monotonic() - last_seen > timeout_seconds:
                print("网页心跳已停止，正在关闭本地服务。", flush=True)
                cleanup_server_outputs(server)
                server.shutdown()
                break

    server.touch_heartbeat = touch_heartbeat  # type: ignore[attr-defined]
    threading.Thread(target=monitor, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description='上市公司财报“智能问数”助手 Web UI')
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--base-dir", type=Path, default=BASE_DIR)
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "outputs/web_assistant")
    parser.add_argument("--knowledge-base-dir", type=Path, default=BASE_DIR / "outputs/task3_langgraph")
    parser.add_argument("--llm-config", type=Path, default=BASE_DIR / "configs/task3_llm.env")
    parser.add_argument("--no-open", action="store_true", help="只启动服务，不自动打开浏览器")
    args = parser.parse_args()

    service = InteractiveTask3Service(
        base_dir=args.base_dir,
        output_dir=args.output_dir,
        knowledge_base_dir=args.knowledge_base_dir,
        llm_config=args.llm_config,
    )
    server = build_server(args.host, args.port, service)
    start_heartbeat_monitor(server)
    url = f"http://{args.host}:{args.port}"
    print(f'上市公司财报“智能问数”助手已启动: {url}', flush=True)
    print("按 Ctrl+C 停止服务。", flush=True)
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。", flush=True)
    finally:
        cleanup_server_outputs(server)
        server.server_close()


if __name__ == "__main__":
    main()
