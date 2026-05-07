"""对比多次游戏会话的路径多样性。

Usage: python scripts/compare_paths.py [--dir data/sessions]
"""
import json
import sys
from pathlib import Path


def load_sessions(sessions_dir: Path) -> list[dict]:
    sessions = []
    for f in sorted(sessions_dir.glob("session_*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            sessions.append(json.load(fh))
    return sessions


def path_signature(session: dict) -> str:
    """将路径事件序列转为可比较的签名。"""
    events = session.get("path_events", [])
    return " → ".join(events) if events else "无关键事件"


def compare(sessions: list[dict]):
    if len(sessions) < 2:
        print(f"仅 {len(sessions)} 次会话记录，需要至少2次才能对比。")
        return

    # 按路径签名分组
    signatures: dict[str, int] = {}
    for s in sessions:
        sig = path_signature(s)
        signatures[sig] = signatures.get(sig, 0) + 1

    unique_paths = len(signatures)
    total = len(sessions)

    print(f"=== 路径多样性分析 ===")
    print(f"总会话数: {total}")
    print(f"不同路径数: {unique_paths}")
    print(f"路径多样性: {'✓ 达标' if unique_paths >= 3 else '✗ 未达标'}（目标≥3条不同路径）")
    print()

    print("路径分布:")
    for sig, count in sorted(signatures.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"  [{count}次, {pct:.0f}%] {sig}")

    print()
    print("=== 各会话详细指标 ===")
    for i, s in enumerate(sessions):
        print(f"\n会话{i+1}: {path_signature(s)}")
        print(f"  延迟: avg={s['avg_latency_ms']:.1f}ms min={s['min_latency_ms']:.1f}ms max={s['max_latency_ms']:.1f}ms")
        if s.get("consistency_checks"):
            rate = s["consistency_passes"] / s["consistency_checks"] * 100
            print(f"  一致性: {rate:.0f}% ({s['consistency_passes']}/{s['consistency_checks']})")
        if s.get("npc_actions_total"):
            er = s["emergence_rate"] * 100
            print(f"  涌现率: {er:.0f}% ({s['npc_actions_emergent']}/{s['npc_actions_total']})")
        print(f"  结果: {s.get('final_result', '?')}")


if __name__ == "__main__":
    sessions_dir = Path(sys.argv[2]) if "--dir" in sys.argv else Path(__file__).parent.parent / "data" / "sessions"
    if not sessions_dir.exists():
        print(f"目录不存在: {sessions_dir}")
        print("请先运行几次游戏生成会话数据。")
        sys.exit(1)
    sessions = load_sessions(sessions_dir)
    compare(sessions)
