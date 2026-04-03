"""Scaffolder - 创建room的文件夹结构和初始文件。

沿用用户已验证的mailbox模式：
  .local_agent_ops/
    agent_mailbox/    固定槽位通信文件
    onboarding/       角色手册
    recovery/         session崩溃恢复文档
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def create_room(
    runtime_root: Path,
    room_id: str,
    workspace: str,
    executor_role: str = "执行人",
    reviewer_role: str = "监督人",
) -> Path:
    """创建完整的room目录结构，返回room根目录路径。"""
    room_dir = runtime_root / "rooms" / room_id
    ops_dir = room_dir / ".local_agent_ops"
    mailbox_dir = ops_dir / "agent_mailbox"
    onboarding_dir = ops_dir / "onboarding"
    recovery_dir = ops_dir / "recovery"

    for d in (mailbox_dir, onboarding_dir, recovery_dir):
        d.mkdir(parents=True, exist_ok=True)

    _write_mailbox_files(mailbox_dir, executor_role, reviewer_role)
    _write_onboarding_files(onboarding_dir, executor_role, reviewer_role, workspace)
    _write_recovery_files(recovery_dir, executor_role, reviewer_role)

    return room_dir


def _write_mailbox_files(
    mailbox_dir: Path,
    executor_role: str,
    reviewer_role: str,
) -> None:
    """创建邮箱固定槽位文件和共享状态文件。"""

    readme = dedent(f"""\
        # 邮箱使用说明

        本目录是 {executor_role} 和 {reviewer_role} 之间的通信邮箱。

        ## 文件说明
        - {executor_role}_给_{reviewer_role}.txt  → {executor_role}的工作汇报/回复
        - {reviewer_role}_给_{executor_role}.txt  → {reviewer_role}的审核结果/反馈
        - 共识状态.txt                           → 双方已达成的共识和当前进度
        - 待决问题.txt                           → 未解决的问题追踪
        - 轮次记录.txt                           → 历次交互的摘要记录

        ## 规则
        - 每个角色只写自己的发件箱，读对方的发件箱
        - 共识状态由双方共同维护
        - 系统不代写任何邮箱内容
    """)

    files = {
        "README.txt": readme,
        f"{executor_role}_给_{reviewer_role}.txt": f"# {executor_role} → {reviewer_role}\n\n（等待{executor_role}写入）\n",
        f"{reviewer_role}_给_{executor_role}.txt": f"# {reviewer_role} → {executor_role}\n\n（等待{reviewer_role}写入）\n",
        "共识状态.txt": "# 共识状态\n\n当前阶段: 初始化\n已完成: 无\n进行中: 无\n待处理: 无\n",
        "待决问题.txt": "# 待决问题\n\n（暂无待决问题）\n",
        "轮次记录.txt": "# 轮次记录\n\n（暂无记录）\n",
    }

    for filename, content in files.items():
        (mailbox_dir / filename).write_text(content, encoding="utf-8")


def _write_onboarding_files(
    onboarding_dir: Path,
    executor_role: str,
    reviewer_role: str,
    workspace: str,
) -> None:
    """创建角色手册。首次onboarding时发给agent。"""

    executor_manual = dedent(f"""\
        # {executor_role}手册

        ## 你的角色
        你是{executor_role}。你负责执行具体任务，产出代码变更、方案文档、问题修复等。

        ## 工作方式
        1. 等待接收具体任务指令，收到任务前不要探索工作区
        2. 接收任务后，仅针对任务相关的文件在工作区 ({workspace}) 中工作
        3. 完成后，将你做的所有事情详细写入你的发件箱
        4. 阅读{reviewer_role}的反馈，按要求修改
        5. 重复直到双方达成共识

        ## 邮箱规则
        - 你的发件箱: {executor_role}_给_{reviewer_role}.txt （只有你写）
        - 你的收件箱: {reviewer_role}_给_{executor_role}.txt （只有你读）
        - 每次写入都要包含：做了什么、改了哪些文件、遇到什么问题、需要对方确认什么
        - 同时维护 共识状态.txt 和 轮次记录.txt

        ## 态度要求
        - 对{reviewer_role}的反馈认真对待，逐条回应
        - 不确定的地方主动提出，记录到 待决问题.txt
        - 如果不同意{reviewer_role}的意见，给出具体理由
    """)

    reviewer_manual = dedent(f"""\
        # {reviewer_role}手册

        ## 你的角色
        你是{reviewer_role}。你负责严格审核{executor_role}的工作产出，确保质量和正确性。

        ## 工作方式
        1. 阅读{executor_role}的发件箱内容
        2. 严格分析，不要迎合，不做空泛表扬
        3. 将审核结果写入你的发件箱
        4. 明确表态：通过 / 需要修改 / 有严重问题

        ## 邮箱规则
        - 你的发件箱: {reviewer_role}_给_{executor_role}.txt （只有你写）
        - 你的收件箱: {executor_role}_给_{reviewer_role}.txt （只有你读）
        - 每次审核都要包含：审核结论、发现的问题、改进建议
        - 有问题记录到 待决问题.txt

        ## 态度要求
        - 严格但公正，每个问题都要有具体依据
        - 不要因为对方修改了就自动通过，重新独立判断
        - 如果没有问题，简明扼要地确认，不需要强行找问题
        - 同意进入下一步时明确说"无异议"或"建议进入下一阶段"
    """)

    (onboarding_dir / f"{executor_role}手册.md").write_text(
        executor_manual, encoding="utf-8"
    )
    (onboarding_dir / f"{reviewer_role}手册.md").write_text(
        reviewer_manual, encoding="utf-8"
    )


def _write_recovery_files(
    recovery_dir: Path,
    executor_role: str,
    reviewer_role: str,
) -> None:
    """创建session崩溃后的恢复引导文档。"""

    for role, other_role in [
        (executor_role, reviewer_role),
        (reviewer_role, executor_role),
    ]:
        content = dedent(f"""\
            # {role}快速回归指引

            你的session因故中断，需要恢复工作状态。请按顺序阅读以下文件：

            1. onboarding/{role}手册.md — 你的角色和职责
            2. agent_mailbox/共识状态.txt — 当前共识和进度
            3. agent_mailbox/轮次记录.txt — 最近的交互记录
            4. agent_mailbox/{other_role}_给_{role}.txt — 对方最新的消息
            5. agent_mailbox/待决问题.txt — 未解决的问题

            阅读完毕后，你应该能够继续之前的工作。
        """)
        (recovery_dir / f"{role}快速回归.txt").write_text(
            content, encoding="utf-8"
        )
