"""Template engine - 加载和渲染提示词模版。

极简设计：从 templates/ 目录加载 .txt 文件，用 {variable} 占位符替换。
不用 Jinja2，不做逻辑分支，纯字符串替换。
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def render(template_name: str, **context: str) -> str:
    """加载模版文件并替换占位符。

    Args:
        template_name: 模版文件名（不含.txt后缀）
        **context: 占位符键值对

    Returns:
        渲染后的字符串
    """
    # 防止路径遍历攻击
    if "/" in template_name or "\\" in template_name or ".." in template_name:
        raise ValueError(f"Invalid template name: {template_name}")
    path = _TEMPLATES_DIR / f"{template_name}.txt"
    resolved = path.resolve()
    if not resolved.is_relative_to(_TEMPLATES_DIR.resolve()):
        raise ValueError(f"Template path escape detected: {template_name}")
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    raw = path.read_text(encoding="utf-8")
    return raw.format(**context)


def list_templates() -> list[str]:
    """列出所有可用模版名称。"""
    return [p.stem for p in sorted(_TEMPLATES_DIR.glob("*.txt"))]


def get_room_context(
    room_dir: Path,
    role: str,
    other_role: str,
    workspace: str,
) -> dict[str, str]:
    """为特定角色构建模版渲染所需的context字典。

    Args:
        room_dir: room根目录
        role: 当前角色名称
        other_role: 对方角色名称
        workspace: 项目工作区路径

    Returns:
        可直接传入 render() 的 context 字典
    """
    ops = room_dir / ".local_agent_ops"
    mailbox = ops / "agent_mailbox"
    onboarding = ops / "onboarding"

    return {
        "workspace": workspace,
        "mailbox_dir": str(mailbox),
        "onboarding_file": str(onboarding / f"{role}手册.md"),
        "outbox_file": str(mailbox / f"{role}_给_{other_role}.txt"),
        "inbox_file": str(mailbox / f"{other_role}_给_{role}.txt"),
        "consensus_file": str(mailbox / "共识状态.txt"),
        "issues_file": str(mailbox / "待决问题.txt"),
        "rounds_file": str(mailbox / "轮次记录.txt"),
        "sender_role": other_role,
    }
