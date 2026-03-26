from __future__ import annotations

import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.services.cli_adapters import CliAdapterError
from backend.app.services.runtime_service import RuntimeWorkflowService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend" / "site"
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
SERVICE = RuntimeWorkflowService(RUNTIME_ROOT)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "LocalAgentWorkflowServer/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            return self._json_response(
                {
                    "status": "ok",
                    "project_root": str(PROJECT_ROOT),
                    "runtime_root": str(RUNTIME_ROOT),
                    "default_workspace": str(PROJECT_ROOT),
                }
            )
        if parsed.path == "/api/providers":
            return self._json_response({"providers": SERVICE.get_provider_statuses()})
        if parsed.path == "/api/last-run":
            return self._json_response({"run": SERVICE.get_last_run()})
        if parsed.path == "/api/runs":
            return self._json_response({"runs": SERVICE.list_runs()})
        if parsed.path.startswith("/api/runs/"):
            run_id = parsed.path.removeprefix("/api/runs/").strip("/")
            if run_id and "/" not in run_id:
                return self._json_response({"run": SERVICE.get_run(run_id)})
        if parsed.path == "/api":
            return self._json_response(
                {
                    "message": "Local Agent Workflow Orchestrator backend is running.",
                    "endpoints": [
                        "/api/health",
                        "/api/providers",
                        "/api/last-run",
                        "/api/runs",
                        "/api/runs/{run_id}",
                        "/api/runs/{run_id}/continue",
                        "/api/runs/{run_id}/plan-approval",
                        "/api/runs/{run_id}/checkpoint-approval",
                        "/api/runs/{run_id}/final-approval",
                        "/api/workflows/plan-cycle",
                        "/api/reviews/repo",
                    ],
                }
            )
        if self._serve_frontend_asset(parsed.path):
            return
        return self._json_response({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/runs":
                result = SERVICE.create_run(
                    task=payload.get("task", "").strip(),
                    workspace=payload.get("workspace", str(PROJECT_ROOT)),
                    executor_provider=payload.get("executor_provider", "codex"),
                    reviewer_provider=payload.get("reviewer_provider", "claude"),
                    verifier_provider=payload.get("verifier_provider") or None,
                    max_plan_rounds=int(payload.get("max_plan_rounds", 2)),
                )
                return self._json_response(result)
            if parsed.path.startswith("/api/runs/"):
                suffix = parsed.path.removeprefix("/api/runs/").strip("/")
                parts = suffix.split("/")
                if len(parts) == 2:
                    run_id, action = parts
                    if action == "continue":
                        return self._json_response(SERVICE.continue_run(run_id))
                    if action == "plan-approval":
                        checkpoint_step_indices = [
                            int(value) for value in payload.get("checkpoint_step_indices", []) if str(value).strip()
                        ]
                        return self._json_response(
                            SERVICE.decide_plan(
                                run_id,
                                approved=bool(payload.get("approved", True)),
                                comment=str(payload.get("comment", "")),
                                checkpoint_step_indices=checkpoint_step_indices,
                            )
                        )
                    if action == "checkpoint-approval":
                        return self._json_response(
                            SERVICE.decide_checkpoint(
                                run_id,
                                step_index=int(payload.get("step_index", 0)),
                                approved=bool(payload.get("approved", True)),
                                comment=str(payload.get("comment", "")),
                            )
                        )
                    if action == "final-approval":
                        return self._json_response(
                            SERVICE.finalize_run(
                                run_id,
                                approved=bool(payload.get("approved", True)),
                                comment=str(payload.get("comment", "")),
                            )
                        )
            if parsed.path == "/api/workflows/plan-cycle":
                result = SERVICE.run_plan_cycle(
                    task=payload.get("task", "").strip(),
                    workspace=payload.get("workspace", str(PROJECT_ROOT)),
                    executor_provider=payload.get("executor_provider", "codex"),
                    reviewer_provider=payload.get("reviewer_provider", "claude"),
                    verifier_provider=payload.get("verifier_provider") or None,
                    auto_revision=bool(payload.get("auto_revision", True)),
                )
                return self._json_response(result)
            if parsed.path == "/api/reviews/repo":
                result = SERVICE.run_repo_review(
                    provider_name=payload.get("provider", "codex"),
                    workspace=payload.get("workspace", str(PROJECT_ROOT)),
                    prompt=payload.get("prompt", "Review the current repository changes strictly."),
                    base_branch=payload.get("base_branch"),
                )
                return self._json_response(result)
            return self._json_response({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except CliAdapterError as exc:
            return self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - server safety path
            return self._json_response({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        body = self.rfile.read(content_length)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _json_response(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_frontend_asset(self, request_path: str) -> bool:
        relative_path = "index.html" if request_path in {"", "/"} else unquote(request_path.lstrip("/"))
        frontend_root = FRONTEND_ROOT.resolve()
        candidate = (frontend_root / relative_path).resolve()
        try:
            candidate.relative_to(frontend_root)
        except ValueError:
            return False
        if not candidate.is_file():
            return False

        body = candidate.read_bytes()
        content_type = guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._send_common_headers()
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), ApiHandler)
    print("Backend listening on http://127.0.0.1:8765")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
