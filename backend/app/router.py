"""Router - 消息路由，系统的核心。

职责极简：发模版给agent → 等完成 → 记录消息 → 切换角色。
不解析agent输出，不做语义分析，不代agent写邮箱。

所有CLI调用都在后台线程执行，HTTP请求立即返回。
前端通过轮询看到新消息。
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Literal

from . import templates
from .scaffolder import create_room
from .session_mgr import SessionManager, Provider
from .store import Store


Turn = Literal["executor", "reviewer"]

logger = logging.getLogger("router")


class Router:
    """消息路由器。"""

    MAX_AUTO_ROUNDS = 20       # 全自动模式最大轮次
    MAX_AUTO_FAILURES = 3      # 连续失败N次自动暂停
    MAX_ROUND_RETRIES = 2      # 单轮失败后重试次数
    AUTO_ROUND_INTERVAL = 2    # 全自动轮次间隔（秒）

    # 这些标记出现在输出中时，视为本轮失败
    _ERROR_MARKERS = (
        "[No output]", "[No response]", "[Session timed out]",
        "[Failed", "[Error", "[Timeout",
    )

    # reviewer 输出包含这些关键词时，视为达成共识，auto 暂停等用户审批
    _CONSENSUS_KEYWORDS = (
        "无异议", "建议进入下一阶段", "共识达成", "审核通过", "可以进入下一步",
        "no objection", "approved", "consensus reached", "ready for next phase",
    )

    def __init__(self, store: Store, session_mgr: SessionManager, runtime_root: Path) -> None:
        self.store = store
        self.session_mgr = session_mgr
        self.runtime_root = runtime_root
        self._busy: dict[str, bool] = {}
        self._auto_mode: dict[str, bool] = {}
        self._auto_paused: set[str] = set()   # 因失败暂停的room，用户发消息可恢复
        self._interrupted: set[str] = set()   # 被用户打断的room，后台线程需检查
        self._room_locks: dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()  # 保护 _room_locks 字典本身
        # Codex首轮获取thread_id后回写DB
        session_mgr.set_cli_session_update_callback(
            lambda sid, cli_id: store.update_session_cli_id(sid, cli_id)
        )

    def _get_lock(self, room_id: str) -> threading.Lock:
        """获取指定 room 的锁（不存在则创建）。"""
        with self._meta_lock:
            if room_id not in self._room_locks:
                self._room_locks[room_id] = threading.Lock()
            return self._room_locks[room_id]

    def is_busy(self, room_id: str) -> bool:
        with self._get_lock(room_id):
            return self._busy.get(room_id, False)

    def _check_interrupted(self, room_id: str) -> bool:
        """检查是否被用户打断。如果是，清除标记并返回 True。"""
        if room_id in self._interrupted:
            self._interrupted.discard(room_id)
            return True
        return False

    def _check_consensus(self, room_id: str, reviewer_output: str) -> bool:
        """检查是否达成共识：reviewer 关键词 或 共识文件标记。"""
        lower = reviewer_output.lower()
        if any(kw in lower for kw in self._CONSENSUS_KEYWORDS):
            return True
        # 检查共识状态文件
        consensus_file = self.runtime_root / "rooms" / room_id / ".local_agent_ops" / "agent_mailbox" / "共识状态.txt"
        if consensus_file.exists():
            content = consensus_file.read_text(encoding="utf-8").lower()
            if any(kw in content for kw in ("共识达成", "全部完成", "consensus reached", "approved")):
                return True
        return False

    def _ensure_session(self, session_row: dict, workspace: str) -> None:
        """确保DB里的session在SessionManager内存中存在（处理server重启）。"""
        self.session_mgr.restore_session(
            session_id=session_row["session_id"],
            role=session_row["role"],
            provider=session_row["provider"],
            cli_session_id=session_row["cli_session_id"],
            workspace=workspace,
        )

    def _run_in_background(self, room_id: str, fn, *args) -> None:
        """在后台线程运行fn，完成后清除busy状态并检查auto继续。"""
        lock = self._get_lock(room_id)

        def wrapper():
            try:
                fn(*args)
            except Exception as exc:
                logger.error("[%s] Background task error: %s", room_id, exc, exc_info=True)
                self.store.add_message(room_id, "system", f"[Error] {exc}")
            finally:
                with lock:
                    self._busy[room_id] = False
                    should_auto = self._auto_mode.get(room_id, False)
                if should_auto:
                    # 重新用后台线程启动 auto loop
                    self._start_auto_thread(room_id)

        with lock:
            if self._busy.get(room_id, False):
                return  # 已经有线程在运行，不重复启动
            self._busy[room_id] = True
        t = threading.Thread(target=wrapper, daemon=True)
        t.start()

    def _make_stream_callback(self, room_id: str, sender: str):
        """创建流式回调：先建占位消息，后续chunk就地更新。"""
        msg_id = self.store.add_message(room_id, sender, "[Thinking...]")
        chunks: list[str] = []

        def on_chunk(event_type: str, content: str):
            chunks.append(content)
            # 每次chunk到达，将所有已收到的内容拼接后更新消息
            self.store.update_message(msg_id, "\n".join(chunks))

        return msg_id, chunks, on_chunk

    def delete_room(self, room_id: str) -> None:
        """删除room：停止auto、清DB、删文件夹。"""
        with self._get_lock(room_id):
            self._auto_mode.pop(room_id, None)
            self._busy.pop(room_id, None)
        # Kill any active processes for this room's sessions
        sessions = self.store.get_sessions_for_room(room_id)
        for s in sessions:
            self.session_mgr.kill_active(s["session_id"])
        self.store.delete_room(room_id)
        room_dir = self.runtime_root / "rooms" / room_id
        if room_dir.exists():
            shutil.rmtree(room_dir, ignore_errors=True)
        # 清理锁
        with self._meta_lock:
            self._room_locks.pop(room_id, None)

    def create_room(
        self,
        room_id: str,
        workspace: str,
        task: str = "",
        executor_role: str = "执行人",
        reviewer_role: str = "监督人",
        executor_provider: Provider = "claude",
        reviewer_provider: Provider = "claude",
    ) -> dict:
        """创建room：脚手架 + 数据库 + 双方session。"""
        logger.info("Creating room %s (workspace=%s, exec=%s, review=%s)",
                     room_id, workspace, executor_provider, reviewer_provider)
        room_dir = create_room(
            self.runtime_root, room_id, workspace,
            executor_role, reviewer_role,
        )

        room = self.store.create_room(
            room_id, workspace, executor_role, reviewer_role, task,
        )

        exec_session = self.session_mgr.create_session(
            role="executor", provider=executor_provider, workspace=workspace,
        )
        review_session = self.session_mgr.create_session(
            role="reviewer", provider=reviewer_provider, workspace=workspace,
        )

        self.store.add_session(
            exec_session.session_id, room_id, "executor",
            executor_provider, exec_session.cli_session_id,
        )
        self.store.add_session(
            review_session.session_id, room_id, "reviewer",
            reviewer_provider, review_session.cli_session_id,
        )

        self.store.add_message(room_id, "system", f"Room created. Task: {task}")
        return self._room_snapshot(room_id)

    def onboard(self, room_id: str) -> dict:
        """Onboarding：后台线程给双方agent发角色手册。立即返回。"""
        room = self.store.get_room(room_id)
        if not room:
            raise ValueError(f"Room not found: {room_id}")

        self.store.add_message(room_id, "system", "Starting onboarding...")
        self._run_in_background(room_id, self._do_onboard, room_id)
        return self._room_snapshot(room_id)

    def _do_onboard(self, room_id: str) -> None:
        """实际执行onboarding（在后台线程中运行）。"""
        logger.info("[%s] Starting onboarding", room_id)
        room = self.store.get_room(room_id)
        room_dir = self.runtime_root / "rooms" / room_id
        executor_role = room["executor_role"]
        reviewer_role = room["reviewer_role"]

        sessions = self.store.get_sessions_for_room(room_id)
        exec_session_row = next(s for s in sessions if s["role"] == "executor")
        review_session_row = next(s for s in sessions if s["role"] == "reviewer")
        self._ensure_session(exec_session_row, room["workspace"])
        self._ensure_session(review_session_row, room["workspace"])

        # Onboard executor
        self.store.add_message(room_id, "system", f"[Onboarding {executor_role}...]")
        exec_ctx = templates.get_room_context(
            room_dir, executor_role, reviewer_role, room["workspace"],
        )
        exec_msg = templates.render("onboarding", **exec_ctx)
        msg_id, chunks, on_chunk = self._make_stream_callback(room_id, "executor")
        exec_result = self.session_mgr.send_message(
            exec_session_row["session_id"], exec_msg, on_chunk=on_chunk,
        )
        # Replace streaming placeholder with final result
        self.store.update_message(msg_id, exec_result.output_text or "\n".join(chunks) or "[No response]")

        # 中断检查：用户在executor onboarding期间点了interrupt
        if self._check_interrupted(room_id):
            self.store.add_message(room_id, "system", "[Onboarding interrupted by user]")
            return

        # Onboard reviewer
        self.store.add_message(room_id, "system", f"[Onboarding {reviewer_role}...]")
        review_ctx = templates.get_room_context(
            room_dir, reviewer_role, executor_role, room["workspace"],
        )
        review_msg = templates.render("onboarding", **review_ctx)
        msg_id2, chunks2, on_chunk2 = self._make_stream_callback(room_id, "reviewer")
        review_result = self.session_mgr.send_message(
            review_session_row["session_id"], review_msg, on_chunk=on_chunk2,
        )
        self.store.update_message(msg_id2, review_result.output_text or "\n".join(chunks2) or "[No response]")

        self.store.update_room_state(room_id, "awaiting_task")
        self.store.add_message(room_id, "system", "Onboarding complete. Please assign a task.")
        logger.info("[%s] Onboarding complete", room_id)

    def run_round(self, room_id: str, turn: Turn) -> dict:
        """执行一轮：后台线程发模版给指定角色。立即返回。"""
        room = self.store.get_room(room_id)
        if not room:
            raise ValueError(f"Room not found: {room_id}")

        self._run_in_background(room_id, self._do_round, room_id, turn)
        return self._room_snapshot(room_id)

    def _do_round(self, room_id: str, turn: Turn, user_note: str = "") -> tuple[bool, str]:
        """实际执行一轮（在后台线程中运行）。返回 (success, output_text)。
        user_note: 用户附加说明，会追加到模板末尾一并发送给 agent。
        """
        logger.info("[%s] Starting round: %s%s", room_id, turn,
                     " (with user note)" if user_note else "")
        room = self.store.get_room(room_id)
        room_dir = self.runtime_root / "rooms" / room_id
        executor_role = room["executor_role"]
        reviewer_role = room["reviewer_role"]

        sessions = self.store.get_sessions_for_room(room_id)
        session_row = next(s for s in sessions if s["role"] == turn)
        self._ensure_session(session_row, room["workspace"])

        if turn == "executor":
            role, other_role = executor_role, reviewer_role
            last_msg = self.store.get_latest_message(room_id)
            template_name = "trigger_execute"
            if last_msg and last_msg["sender"] == "reviewer":
                template_name = "trigger_respond"
        else:
            role, other_role = reviewer_role, executor_role
            template_name = "trigger_review"

        ctx = templates.get_room_context(room_dir, role, other_role, room["workspace"])
        message = templates.render(template_name, **ctx)

        if user_note:
            message += f"\n\n[用户补充说明]\n{user_note}"

        self.store.add_message(room_id, "system", f"[Triggering {role}...]")
        msg_id, chunks, on_chunk = self._make_stream_callback(room_id, turn)
        result = self.session_mgr.send_message(
            session_row["session_id"], message, on_chunk=on_chunk,
        )
        output = result.output_text or "\n".join(chunks) or "[No response]"
        self.store.update_message(msg_id, output)

        # 判定是否成功
        if not result.success:
            logger.warning("[%s] Round %s failed (result.success=False)", room_id, turn)
            return (False, output)
        if any(output.startswith(m) or output == m for m in self._ERROR_MARKERS):
            logger.warning("[%s] Round %s failed (error marker detected)", room_id, turn)
            return (False, output)
        logger.info("[%s] Round %s completed (%d chars)", room_id, turn, len(output))
        return (True, output)

    def approve(self, room_id: str, comment: str = "") -> dict:
        """用户审批：确认进入下一阶段。"""
        room = self.store.get_room(room_id)
        if not room:
            raise ValueError(f"Room not found: {room_id}")

        msg = f"[Approved] {comment}" if comment else "[Approved]"
        self.store.add_message(room_id, "user", msg)

        if room["state"] == "awaiting_approval":
            self.store.update_room_state(room_id, "completed")
            self.store.add_message(room_id, "system", "Run completed.")
        else:
            self.store.add_message(room_id, "system", "Approval noted. Continuing.")

        return self._room_snapshot(room_id)

    def reject(self, room_id: str, comment: str = "") -> dict:
        """用户驳回：要求继续修改。"""
        room = self.store.get_room(room_id)
        if not room:
            raise ValueError(f"Room not found: {room_id}")

        msg = f"[Rejected] {comment}" if comment else "[Rejected]"
        self.store.add_message(room_id, "user", msg)
        self.store.update_room_state(room_id, "working")
        self.store.add_message(room_id, "system", "Rejection noted. Back to working.")

        return self._room_snapshot(room_id)

    def user_message(self, room_id: str, message: str, target: Turn | None = None) -> dict:
        """用户直接干预：发消息给特定agent。"""
        logger.info("[%s] User message → %s (%d chars)", room_id, target or "broadcast", len(message))
        room = self.store.get_room(room_id)
        if not room:
            raise ValueError(f"Room not found: {room_id}")

        self.store.add_message(room_id, "user", message)

        # 如果auto因失败暂停，用户发任何消息即恢复auto
        if room_id in self._auto_paused:
            self._auto_paused.discard(room_id)
            with self._get_lock(room_id):
                self._auto_mode[room_id] = True
            self.store.add_message(room_id, "system", "[Auto resumed by user — continuing...]")
            if not self.is_busy(room_id):
                self._start_auto_thread(room_id)
            return self._room_snapshot(room_id)

        if target:
            if self.is_busy(room_id):
                self.store.add_message(room_id, "system", "[Agent is busy, message queued — use Interrupt to force stop]")
            else:
                self._run_in_background(room_id, self._do_round, room_id, target, message)

        return self._room_snapshot(room_id)

    def assign_task(self, room_id: str, task: str) -> dict:
        """用户下发任务给执行人（onboard后的第一步）。"""
        logger.info("[%s] Task assigned (%d chars)", room_id, len(task))
        room = self.store.get_room(room_id)
        if not room:
            raise ValueError(f"Room not found: {room_id}")

        self.store.add_message(room_id, "user", task)
        self.store.update_room_state(room_id, "working")

        self._run_in_background(room_id, self._do_assign_task, room_id, task)
        return self._room_snapshot(room_id)

    def _do_assign_task(self, room_id: str, task: str) -> None:
        """后台执行：将任务发给执行人。"""
        room = self.store.get_room(room_id)
        room_dir = self.runtime_root / "rooms" / room_id
        executor_role = room["executor_role"]
        reviewer_role = room["reviewer_role"]

        sessions = self.store.get_sessions_for_room(room_id)
        session_row = next(s for s in sessions if s["role"] == "executor")
        self._ensure_session(session_row, room["workspace"])

        ctx = templates.get_room_context(room_dir, executor_role, reviewer_role, room["workspace"])
        trigger = templates.render("trigger_execute", **ctx)
        message = f"用户下发了以下任务：\n\n{task}\n\n{trigger}"

        self.store.add_message(room_id, "system", f"[Assigning task to {executor_role}...]")
        msg_id, chunks, on_chunk = self._make_stream_callback(room_id, "executor")
        result = self.session_mgr.send_message(
            session_row["session_id"], message, on_chunk=on_chunk,
        )
        self.store.update_message(msg_id, result.output_text or "\n".join(chunks) or "[No response]")

        # 如果是auto mode，继续触发reviewer
        with self._get_lock(room_id):
            is_auto = self._auto_mode.get(room_id, False)
        if is_auto:
            self._do_round(room_id, "reviewer")
            self._auto_loop(room_id)

    def _start_auto_thread(self, room_id: str) -> None:
        """启动 auto-loop 后台线程（内部方法）。"""
        lock = self._get_lock(room_id)
        with lock:
            if self._busy.get(room_id, False):
                return
            self._busy[room_id] = True

        def _auto_wrapper():
            try:
                self._auto_loop(room_id)
            except Exception as exc:
                logger.error("[%s] Auto-loop crashed: %s", room_id, exc, exc_info=True)
                self.store.add_message(room_id, "system", f"[Auto Error] {exc}")
            finally:
                with lock:
                    self._busy[room_id] = False

        threading.Thread(target=_auto_wrapper, daemon=True).start()

    def start_auto(self, room_id: str) -> dict:
        """开启Full-Auto模式。"""
        logger.info("[%s] Full-Auto mode ON", room_id)
        room = self.store.get_room(room_id)
        if not room:
            raise ValueError(f"Room not found: {room_id}")

        self._auto_paused.discard(room_id)
        with self._get_lock(room_id):
            self._auto_mode[room_id] = True
        self.store.add_message(room_id, "system", "[Full-Auto mode ON — click Pause to stop]")

        if not self.is_busy(room_id):
            self._start_auto_thread(room_id)

        return self._room_snapshot(room_id)

    def stop_auto(self, room_id: str) -> dict:
        """停止Full-Auto模式。"""
        logger.info("[%s] Full-Auto mode OFF", room_id)
        self._auto_paused.discard(room_id)
        with self._get_lock(room_id):
            self._auto_mode[room_id] = False
        self.store.add_message(room_id, "system", "[Full-Auto mode OFF — paused]")
        return self._room_snapshot(room_id)

    def interrupt(self, room_id: str) -> dict:
        """用户打断：强制终止当前运行的agent，清除所有状态。"""
        logger.warning("[%s] User interrupt — killing active agents", room_id)
        # 标记中断，让后台线程在检查点停下
        self._interrupted.add(room_id)
        # 停止 auto mode
        with self._get_lock(room_id):
            self._auto_mode[room_id] = False
            self._busy[room_id] = False

        # Kill 所有活跃进程
        sessions = self.store.get_sessions_for_room(room_id)
        for s in sessions:
            self.session_mgr.kill_active(s["session_id"])

        self.store.add_message(room_id, "system", "[User interrupted — all agents stopped]")
        return self._room_snapshot(room_id)

    def _auto_loop(self, room_id: str) -> None:
        """全自动循环：executor → reviewer → executor → ... 直到用户暂停。"""
        logger.info("[%s] Auto-loop started", room_id)
        fail_count = 0
        round_count = 0

        while True:
            # 检查是否应该继续
            with self._get_lock(room_id):
                if not self._auto_mode.get(room_id, False):
                    break
            if self._check_interrupted(room_id):
                break

            if round_count >= self.MAX_AUTO_ROUNDS:
                self.store.add_message(
                    room_id, "system",
                    f"[Auto stopped: reached max {self.MAX_AUTO_ROUNDS} rounds]",
                )
                with self._get_lock(room_id):
                    self._auto_mode[room_id] = False
                break

            # 判断轮到谁
            last = self.store.get_latest_message(room_id)
            if not last or last["sender"] in ("system", "user", "reviewer"):
                turn = "executor"
            else:
                turn = "reviewer"

            try:
                success, output = self._do_round(room_id, turn)

                # 失败时重试同一轮，最多 MAX_ROUND_RETRIES 次
                if not success:
                    for retry in range(1, self.MAX_ROUND_RETRIES + 1):
                        self.store.add_message(
                            room_id, "system",
                            f"[Retry {retry}/{self.MAX_ROUND_RETRIES} for {turn}...]",
                        )
                        time.sleep(self.AUTO_ROUND_INTERVAL)
                        with self._get_lock(room_id):
                            if not self._auto_mode.get(room_id, False):
                                break
                        success, output = self._do_round(room_id, turn)
                        if success:
                            break

                if success:
                    fail_count = 0
                    round_count += 1

                    # reviewer 完成后检查是否达成共识
                    if turn == "reviewer" and self._check_consensus(room_id, output):
                        self.store.add_message(
                            room_id, "system",
                            "[Consensus detected — auto paused, awaiting user approval]",
                        )
                        self.store.update_room_state(room_id, "awaiting_approval")
                        with self._get_lock(room_id):
                            self._auto_mode[room_id] = False
                        break
                else:
                    fail_count += 1
                    self.store.add_message(
                        room_id, "system",
                        f"[{turn} failed after {self.MAX_ROUND_RETRIES} retries]",
                    )

            except Exception as exc:
                logger.error("[%s] Auto round exception: %s", room_id, exc, exc_info=True)
                fail_count += 1
                self.store.add_message(room_id, "system", f"[Auto round failed: {exc}]")

            if fail_count >= self.MAX_AUTO_FAILURES:
                self.store.add_message(
                    room_id, "system",
                    f"[Auto paused: {self.MAX_AUTO_FAILURES} consecutive failures — send any message to resume]",
                )
                with self._get_lock(room_id):
                    self._auto_mode[room_id] = False
                self._auto_paused.add(room_id)
                break

            # 再次检查 + 轮间间隔
            with self._get_lock(room_id):
                if not self._auto_mode.get(room_id, False):
                    break
            time.sleep(self.AUTO_ROUND_INTERVAL)

    def _do_intervene(self, room_id: str, target: Turn, message: str) -> None:
        """用户干预的后台执行。"""
        room = self.store.get_room(room_id)
        sessions = self.store.get_sessions_for_room(room_id)
        session_row = next(s for s in sessions if s["role"] == target)
        self._ensure_session(session_row, room["workspace"])
        prefixed = f"[用户直接指令] 以下是用户对你的直接消息，请认真对待并回复：\n\n{message}"
        msg_id, chunks, on_chunk = self._make_stream_callback(room_id, target)
        result = self.session_mgr.send_message(
            session_row["session_id"], prefixed, on_chunk=on_chunk,
        )
        self.store.update_message(msg_id, result.output_text or "\n".join(chunks) or "[No response]")

    def _room_snapshot(self, room_id: str) -> dict:
        """构建room当前状态的快照。"""
        room = self.store.get_room(room_id)
        messages = self.store.get_messages(room_id)
        sessions = self.store.get_sessions_for_room(room_id)

        mailbox_files = {}
        room_dir = self.runtime_root / "rooms" / room_id
        mailbox_dir = room_dir / ".local_agent_ops" / "agent_mailbox"
        if mailbox_dir.exists():
            for f in mailbox_dir.glob("*.txt"):
                mailbox_files[f.name] = f.read_text(encoding="utf-8")

        with self._get_lock(room_id):
            busy = self._busy.get(room_id, False)
            auto_mode = self._auto_mode.get(room_id, False)

        return {
            "room": room,
            "messages": messages,
            "sessions": sessions,
            "mailbox_files": mailbox_files,
            "busy": busy,
            "auto_mode": auto_mode,
        }
