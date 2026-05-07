import json
import time
import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class SessionReport:
    avg_latency_ms: float = 0
    min_latency_ms: float = 0
    max_latency_ms: float = 0
    p50_latency_ms: float = 0
    p99_latency_ms: float = 0
    total_llm_calls: int = 0
    consistency_checks: int = 0
    consistency_passes: int = 0
    npc_actions_total: int = 0
    npc_actions_emergent: int = 0
    player_talks: dict[str, int] = field(default_factory=dict)
    path_events: list[str] = field(default_factory=list)
    player_topics: set[str] = field(default_factory=set)
    final_result: str = ""


class MetricsTracker:
    def __init__(self):
        self._latencies: list[tuple[str, float]] = []  # (event_type, ms)
        self._consistency_total: int = 0
        self._consistency_pass: int = 0
        self._npc_actions: list[dict] = []  # {npc, topic, is_emergent: bool}
        self._player_talks: dict[str, int] = {}  # {npc: count}
        self._player_topics: set[str] = set()
        self._path_events: list[str] = []
        self._final_result: str = ""
        self._start_time: float = time.time()

    def record_latency(self, event_type: str, ms: float):
        self._latencies.append((event_type, ms))

    def record_npc_memory(self, npc: str, action: str, n_memories: int):
        pass  # lightweight hook, data captured elsewhere

    def record_npc_action(self, npc: str, topic: str):
        entry = {"npc": npc, "topic": topic, "is_emergent": False}
        self._npc_actions.append(entry)

    def record_player_talk(self, npc: str):
        self._player_talks[npc] = self._player_talks.get(npc, 0) + 1

    def record_player_topic(self, topic: str):
        self._player_topics.add(topic)

    def record_submission(self, answer: str, result: str):
        self._final_result = result

    def mark_npc_action_emergent(self, index: int):
        if 0 <= index < len(self._npc_actions):
            self._npc_actions[index]["is_emergent"] = True

    def add_path_event(self, event: str):
        self._path_events.append(event)

    def record_consistency_check(self, passed: bool):
        self._consistency_total += 1
        if passed:
            self._consistency_pass += 1

    def get_total_player_talks(self) -> int:
        return sum(self._player_talks.values())

    def end_session(self) -> SessionReport:
        report = SessionReport()
        report.total_llm_calls = len(self._latencies)
        report.player_talks = dict(self._player_talks)
        report.path_events = list(self._path_events)
        report.final_result = self._final_result

        if self._latencies:
            ms_values = sorted(ms for _, ms in self._latencies)
            report.avg_latency_ms = sum(ms_values) / len(ms_values)
            report.min_latency_ms = ms_values[0]
            report.max_latency_ms = ms_values[-1]
            p50_idx = int(len(ms_values) * 0.5)
            p99_idx = int(len(ms_values) * 0.99)
            report.p50_latency_ms = ms_values[min(p50_idx, len(ms_values) - 1)]
            report.p99_latency_ms = ms_values[min(p99_idx, len(ms_values) - 1)]

        report.consistency_checks = self._consistency_total
        report.consistency_passes = self._consistency_pass

        report.npc_actions_total = len(self._npc_actions)
        report.npc_actions_emergent = sum(
            1 for a in self._npc_actions if a["is_emergent"]
        )
        report.player_topics = set(self._player_topics)

        return report

    def to_json(self, path: str | Path):
        report = self.end_session()
        data = {
            "session_start": self._start_time,
            "session_end": time.time(),
            "avg_latency_ms": report.avg_latency_ms,
            "min_latency_ms": report.min_latency_ms,
            "max_latency_ms": report.max_latency_ms,
            "p50_latency_ms": report.p50_latency_ms,
            "p99_latency_ms": report.p99_latency_ms,
            "total_llm_calls": report.total_llm_calls,
            "consistency_checks": report.consistency_checks,
            "consistency_passes": report.consistency_passes,
            "consistency_rate": (
                report.consistency_passes / max(report.consistency_checks, 1)
            ),
            "npc_actions_total": report.npc_actions_total,
            "npc_actions_emergent": report.npc_actions_emergent,
            "emergence_rate": (
                report.npc_actions_emergent / max(report.npc_actions_total, 1)
            ),
            "player_talks": report.player_talks,
            "path_events": report.path_events,
            "final_result": report.final_result,
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data

    def format_report(self) -> str:
        report = self.end_session()
        lines = [
            "",
            "=== 度量报告 ===",
        ]

        if report.total_llm_calls > 0:
            avg_s = report.avg_latency_ms / 1000
            min_s = report.min_latency_ms / 1000
            max_s = report.max_latency_ms / 1000
            lines.append(
                f"响应延迟: avg={avg_s:.1f}s | "
                f"min={min_s:.1f}s | max={max_s:.1f}s"
                + ("  ✓" if avg_s < 3.0 else "  ✗（目标<3s）")
            )
        else:
            lines.append("响应延迟: 无LLM调用")

        if report.consistency_checks > 0:
            rate = report.consistency_passes / report.consistency_checks * 100
            lines.append(
                f"记忆一致性: {rate:.0f}% ({report.consistency_passes}/{report.consistency_checks})"
                + ("  ✓" if rate >= 85 else "  ✗（目标>85%）")
            )
        else:
            lines.append("记忆一致性: 未检测")

        if report.npc_actions_total > 0:
            emerge_rate = report.npc_actions_emergent / report.npc_actions_total * 100
            lines.append(
                f"涌现率: {emerge_rate:.0f}% ({report.npc_actions_emergent}/{report.npc_actions_total}个话题玩家未触及)"
                + ("  ✓" if emerge_rate >= 30 else "  ✗（目标>30%）")
            )
        else:
            lines.append("涌现率: NPC无自主行动")

        if report.path_events:
            path_str = " → ".join(report.path_events)
            lines.append(f"路径: {path_str}")
            lines.append("（运行 scripts/compare_paths.py 进行跨局路径多样性对比）")

        lines.append("")
        return "\n".join(lines)


# 全局单例
_tracker: MetricsTracker | None = None


def get_metrics() -> MetricsTracker:
    global _tracker
    if _tracker is None:
        _tracker = MetricsTracker()
    return _tracker


def reset_metrics():
    global _tracker
    _tracker = MetricsTracker()
