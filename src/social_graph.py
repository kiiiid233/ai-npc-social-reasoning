import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Relationship:
    trust: float = 0.0   # -1 ~ 1
    liking: float = 0.0   # -1 ~ 1
    debt: float = 0.0     # 0 ~ 1

    def clamp(self):
        self.trust = max(-1, min(1, self.trust))
        self.liking = max(-1, min(1, self.liking))
        self.debt = max(0, min(1, self.debt))

    def summary(self) -> str:
        parts = []
        if self.trust > 0.3:
            parts.append("信任")
        elif self.trust < -0.3:
            parts.append("不信任")
        if self.liking > 0.3:
            parts.append("有好感")
        elif self.liking < -0.3:
            parts.append("厌恶")
        if self.debt > 0.3:
            parts.append("觉得亏欠")
        return "，".join(parts) if parts else "态度中立"


# Event types and their effects on relationship dimensions
EVENT_EFFECTS = {
    "help":       {"trust": 0.15, "liking": 0.2,  "debt": 0.1},
    "harm":       {"trust": -0.2, "liking": -0.3, "debt": 0.0},
    "lie":        {"trust": -0.3, "liking": -0.1, "debt": 0.0},
    "gift":       {"trust": 0.1,  "liking": 0.15, "debt": 0.2},
    "insult":     {"trust": -0.1, "liking": -0.25,"debt": 0.0},
    "promise":    {"trust": 0.1,  "liking": 0.05, "debt": 0.0},
    "betray":     {"trust": -0.4, "liking": -0.4, "debt": 0.0},
    "chat_positive": {"trust": 0.05, "liking": 0.1, "debt": 0.0},
    "chat_negative": {"trust": -0.05, "liking": -0.1, "debt": 0.0},
}


class SocialGraph:
    def __init__(self):
        # key: tuple(sorted names), value: Relationship
        self._edges: dict[tuple[str, str], Relationship] = {}

    def _key(self, a: str, b: str) -> tuple[str, str]:
        return tuple(sorted([a, b]))

    def init_relationship(self, a: str, b: str, trust: float = 0.0, liking: float = 0.0, debt: float = 0.0):
        key = self._key(a, b)
        self._edges[key] = Relationship(trust=trust, liking=liking, debt=debt)

    def get(self, a: str, b: str) -> Relationship:
        key = self._key(a, b)
        if key not in self._edges:
            self._edges[key] = Relationship()
        return self._edges[key]

    def update(self, from_npc: str, to_npc: str, event_type: str):
        if event_type not in EVENT_EFFECTS:
            logger.warning("Unknown event type: %s", event_type)
            return

        rel = self.get(from_npc, to_npc)
        effects = EVENT_EFFECTS[event_type]
        rel.trust += effects["trust"]
        rel.liking += effects["liking"]
        rel.debt += effects["debt"]
        rel.clamp()
        logger.info("%s → %s: %s (信任%.2f 好感%.2f)", from_npc, to_npc, event_type, rel.trust, rel.liking)

    def get_relationship_summary(self, from_npc: str, to_npc: str) -> str:
        rel = self.get(from_npc, to_npc)
        return f"{from_npc}对{to_npc}：{rel.summary()}（信任{rel.trust:.1f} 好感{rel.liking:.1f}）"

    def get_all_summaries(self, npc_name: str) -> list[str]:
        summaries = []
        for key, rel in self._edges.items():
            a, b = key
            other = b if a == npc_name else a if b == npc_name else None
            if other:
                rel = self.get(npc_name, other)
                summaries.append(f"- {other}：{rel.summary()}（信任{rel.trust:.1f} 好感{rel.liking:.1f}）")
        return summaries

    def to_dict(self) -> dict:
        return {
            f"{a},{b}": {"trust": r.trust, "liking": r.liking, "debt": r.debt}
            for (a, b), r in self._edges.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SocialGraph":
        graph = cls()
        for key, vals in data.items():
            a, b = key.split(",")
            graph.init_relationship(a, b, **vals)
        return graph
