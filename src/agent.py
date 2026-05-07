import json
import logging
import random
from pathlib import Path
from typing import Optional

from llm_client import LLMClient, get_llm_client
from memory import MemorySystem
from social_graph import SocialGraph

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


class NPCAgent:
    def __init__(
        self,
        name: str,
        role: str,
        personality: str,
        goal: str,
        secret: str,
        memory: MemorySystem,
        social_graph: SocialGraph,
        llm: LLMClient | None = None,
    ):
        self.name = name
        self.role = role
        self.personality = personality
        self.goal = goal
        self.secret = secret
        self.memory = memory
        self.social_graph = social_graph
        self.llm = llm or get_llm_client()

        self._conversation_history: list[dict] = []

    def _build_system_prompt(self, speaker: str | None = None) -> str:
        template = (PROMPTS_DIR / "npc_system.txt").read_text(encoding="utf-8")
        memories = self.memory.get_recent(5)
        rel_summaries = self.social_graph.get_all_summaries(self.name)

        # Include speaker-specific relationship if applicable
        speaker_rel = ""
        if speaker and speaker != "系统":
            speaker_rel = f"\n你对{speaker}的态度：{self.social_graph.get(self.name, speaker).summary()}"

        return template.format(
            name=self.name,
            role=self.role,
            personality=self.personality,
            goal=self.goal,
            secret=self.secret,
            relationships="\n".join(rel_summaries) + speaker_rel,
            memories="\n".join(f"- {m}" for m in memories) if memories else "暂无",
        ) + '\n\n用JSON回复：{"reply": "你的自然语言回复", "sentiment": "chat_positive/chat_negative/neutral", "emotion": "你当前的情绪"}'

    async def respond(self, message: str, speaker: str = "玩家") -> str:
        """Respond to a message from the speaker."""
        # Retrieve relevant memories
        relevant = self.memory.search(f"{speaker} {message}", top_k=3)
        for mem in relevant:
            if mem not in self.memory.get_recent(5):
                self._conversation_history.append({
                    "role": "system",
                    "content": f"（回忆起：{mem}）",
                })

        # Build messages
        system_prompt = self._build_system_prompt(speaker)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._conversation_history[-10:])  # keep last 10 turns
        messages.append({"role": "user", "content": f"{speaker}对你说：{message}"})

        # Call LLM (JSON mode for structured output)
        raw = await self.llm.chat(messages, json_output=True)
        try:
            import json as _json
            parsed = _json.loads(raw)
            response = parsed.get("reply", raw)
            event_type = parsed.get("sentiment", "neutral")
        except Exception:
            response = raw
            event_type = None

        # Store memory
        self.memory.store(f"{speaker}对我说：{message}", importance=0.6)
        self.memory.store(f"我回应{speaker}：{response}", importance=0.5)

        # 埋点：记忆存储事件 + 路径事件（玩家触及NPC秘密）
        try:
            from metrics import get_metrics
            m = get_metrics()
            m.record_npc_memory(self.name, "store", 1)
            secret_keywords = ["锤子", "偷", "赌", "抵押", "欠", "看到", "打烊", "债主", "晚上", "半夜", "撒谎", "说谎", "真相", "秘密"]
            if any(kw in message for kw in secret_keywords):
                m.add_path_event(f"触及{self.name}关键话题")
        except ImportError:
            pass

        # Update conversation history
        self._conversation_history.append({"role": "user", "content": f"{speaker}：{message}"})
        self._conversation_history.append({"role": "assistant", "content": response})

        # Update relationship using LLM-judged sentiment
        if event_type:
            self.social_graph.update(self.name, speaker, event_type)

        return response

    async def tick(self, day: int, other_agents: list["NPCAgent"], force: bool = False) -> Optional[dict]:
        """Agent autonomously decides an action each game tick."""
        # Random chance to act (not every tick), unless forced
        if not force and random.random() > 0.7:
            return None

        template = (PROMPTS_DIR / "npc_tick.txt").read_text(encoding="utf-8")
        memories = self.memory.get_recent(3)
        rel_summaries = self.social_graph.get_all_summaries(self.name)

        system_prompt = template.format(
            name=self.name,
            day=day,
            personality=self.personality,
            goal=self.goal,
            relationships="\n".join(rel_summaries),
            memories="\n".join(f"- {m}" for m in memories) if memories else "暂无",
        )

        messages = [{"role": "system", "content": system_prompt}]
        result = await self.llm.chat(messages, json_output=True)

        try:
            action = json.loads(result)
        except json.JSONDecodeError:
            return None

        if not action.get("should_act"):
            return None

        # If talking to another NPC, let target respond, store memories, update relationships
        if action.get("action_type") == "talk" and action.get("target"):
            target_name = action["target"]
            target_agent = next((a for a in other_agents if a.name == target_name), None)
            if target_agent:
                content = action.get("content", "……")
                self.memory.store(f"我主动找了{target_name}，说了：{content}", importance=0.4)

                # Target NPC actually responds via LLM
                target_response = await target_agent.respond(content, speaker=self.name)
                action["target_response"] = target_response

                # Update social graph (both directions)
                event_type = action.get("event_type", "chat_positive")
                self.social_graph.update(self.name, target_name, event_type)

                # 埋点：NPC主动透露线索
                try:
                    from metrics import get_metrics
                    clue_keywords = ["锤子", "偷", "赌", "抵押", "欠", "看到", "打烊", "债主", "晚上", "半夜", "撒谎", "说谎"]
                    if any(kw in content for kw in clue_keywords):
                        get_metrics().add_path_event(f"{self.name}主动透露线索给{target_name}")
                except ImportError:
                    pass

        return action

    def reset_conversation(self):
        self._conversation_history.clear()
