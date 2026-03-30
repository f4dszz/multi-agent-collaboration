"""快速验证 scaffolder 是否正确创建目录结构。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.scaffolder import create_room

runtime = Path(__file__).resolve().parent.parent / "runtime"
room_dir = create_room(runtime, "test-room-001", workspace="D:/workSpace/test-project")

print("=== Directory Structure ===")
for p in sorted(room_dir.rglob("*")):
    rel = p.relative_to(room_dir)
    prefix = "  " * (len(rel.parts) - 1)
    kind = "[DIR]" if p.is_dir() else "[FILE]"
    print(f"{prefix}{kind} {rel.name}")

print("\n=== Mailbox Files ===")
mailbox = room_dir / ".local_agent_ops" / "agent_mailbox"
for f in sorted(mailbox.glob("*.txt")):
    print(f"\n--- {f.name} ---")
    print(f.read_text(encoding="utf-8")[:200])
