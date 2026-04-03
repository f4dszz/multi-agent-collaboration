"""HTTP Server - 精简的6个端点。

GET  /api/health
GET  /api/rooms              → 列出所有room
POST /api/rooms              → 创建room
GET  /api/rooms/{id}         → room详情 + 消息流 + 邮箱文件
POST /api/rooms/{id}/next    → 触发下一轮
POST /api/rooms/{id}/approve → 用户审批/驳回/干预
"""

from __future__ import annotations

import json
import re
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.router import Router
from app.session_mgr import SessionManager
from app.store import Store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = PROJECT_ROOT / "backend" / "runtime"
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "site"
DB_PATH = RUNTIME_ROOT / "orchestrator.db"


def create_app() -> tuple[Store, SessionManager, Router]:
    store = Store(DB_PATH)
    store.initialize()
    session_mgr = SessionManager()
    router = Router(store, session_mgr, RUNTIME_ROOT)
    return store, session_mgr, router


store, session_mgr, router = create_app()


class Handler(BaseHTTPRequestHandler):
    """极简HTTP handler。"""

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")

        if path == "/api/health":
            self._json_response({"status": "ok", "runtime_root": str(RUNTIME_ROOT)})

        elif path == "/api/rooms":
            rooms = store.list_rooms()
            self._json_response(rooms)

        elif (m := re.match(r"^/api/rooms/([^/]+)$", path)):
            room_id = m.group(1)
            snapshot = router._room_snapshot(room_id)
            if snapshot["room"] is None:
                self._json_response({"error": "Room not found"}, status=404)
            else:
                self._json_response(snapshot)

        elif path == "" or path == "/" or path == "/index.html":
            self._serve_static("index.html")
        elif path.startswith("/"):
            self._serve_static(path.lstrip("/"))
        else:
            self._json_response({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        body = self._read_body()

        try:
            if path == "/api/rooms":
                room_id = body.get("room_id", "")
                workspace = body.get("workspace", "")
                task = body.get("task", "")
                executor_role = body.get("executor_role", "执行人")
                reviewer_role = body.get("reviewer_role", "监督人")
                executor_provider = body.get("executor_provider", "claude")
                reviewer_provider = body.get("reviewer_provider", "claude")

                if not room_id or not workspace:
                    self._json_response({"error": "room_id and workspace required"}, status=400)
                    return

                snapshot = router.create_room(
                    room_id, workspace, task,
                    executor_role, reviewer_role,
                    executor_provider, reviewer_provider,
                )
                self._json_response(snapshot, status=201)

            elif (m := re.match(r"^/api/rooms/([^/]+)/next$", path)):
                room_id = m.group(1)
                action = body.get("action", "auto")

                if action == "onboard":
                    snapshot = router.onboard(room_id)
                elif action == "auto":
                    # 自动判断轮到谁
                    room = store.get_room(room_id)
                    last = store.get_latest_message(room_id)
                    if not last or last["sender"] in ("system", "user", "reviewer"):
                        turn = "executor"
                    else:
                        turn = "reviewer"
                    snapshot = router.run_round(room_id, turn)
                elif action in ("executor", "reviewer"):
                    snapshot = router.run_round(room_id, action)
                else:
                    self._json_response({"error": f"Unknown action: {action}"}, status=400)
                    return

                self._json_response(snapshot)

            elif (m := re.match(r"^/api/rooms/([^/]+)/task$", path)):
                room_id = m.group(1)
                task = body.get("task", "")
                if not task:
                    self._json_response({"error": "task is required"}, status=400)
                    return
                snapshot = router.assign_task(room_id, task)
                self._json_response(snapshot)

            elif (m := re.match(r"^/api/rooms/([^/]+)/auto$", path)):
                room_id = m.group(1)
                action = body.get("action", "start")
                if action == "start":
                    snapshot = router.start_auto(room_id)
                else:
                    snapshot = router.stop_auto(room_id)
                self._json_response(snapshot)

            elif (m := re.match(r"^/api/rooms/([^/]+)/interrupt$", path)):
                room_id = m.group(1)
                snapshot = router.interrupt(room_id)
                self._json_response(snapshot)

            elif (m := re.match(r"^/api/rooms/([^/]+)/approve$", path)):
                room_id = m.group(1)
                decision = body.get("decision", "approve")
                comment = body.get("comment", "")
                target = body.get("target")
                message = body.get("message", "")

                if decision == "approve":
                    snapshot = router.approve(room_id, comment)
                elif decision == "reject":
                    snapshot = router.reject(room_id, comment)
                elif decision == "intervene" and message:
                    snapshot = router.user_message(room_id, message, target)
                else:
                    self._json_response({"error": "Invalid decision"}, status=400)
                    return

                self._json_response(snapshot)

            else:
                self._json_response({"error": "Not found"}, status=404)

        except Exception as exc:
            traceback.print_exc()
            self._json_response({"error": str(exc)}, status=500)

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")

        try:
            if (m := re.match(r"^/api/rooms/([^/]+)$", path)):
                room_id = m.group(1)
                router.delete_room(room_id)
                self._json_response({"deleted": room_id})
            else:
                self._json_response({"error": "Not found"}, status=404)
        except Exception as exc:
            traceback.print_exc()
            self._json_response({"error": str(exc)}, status=500)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _json_response(self, data, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > 1_000_000:  # 1MB 限制
            raise ValueError("Request body too large")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return json.loads(raw)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _serve_static(self, rel_path: str) -> None:
        file_path = (FRONTEND_DIR / rel_path).resolve()
        # 防止路径遍历
        if not file_path.is_relative_to(FRONTEND_DIR.resolve()):
            self._json_response({"error": "Forbidden"}, status=403)
            return
        if not file_path.is_file():
            self._json_response({"error": "Not found"}, status=404)
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }
        ct = content_types.get(file_path.suffix, "application/octet-stream")
        data = file_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main() -> None:
    host, port = "127.0.0.1", 8765
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Server running at http://{host}:{port}")
    print(f"Runtime root: {RUNTIME_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        print("Cleaning up active processes...")
        session_mgr.cleanup_all()
        server.shutdown()
        store.close()
        print("Done.")


if __name__ == "__main__":
    main()
