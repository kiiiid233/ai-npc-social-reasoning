import json
import logging
from pathlib import Path
from typing import Optional

from agent import NPCAgent
from memory import MemorySystem
from social_graph import SocialGraph

logger = logging.getLogger(__name__)


class World:
    def __init__(self, config_path: str = "./data/npc_configs.json"):
        self.day = 1
        self.max_days = 3
        self.tick_count = 0
        self.ticks_per_day = 4
        self.game_over = False
        self.social_graph = SocialGraph()
        self.agents: dict[str, NPCAgent] = {}
        self.npc_descriptions: dict[str, str] = {}  # player-visible intros

        self._load_config(Path(config_path))
        self._init_relationships()

    def _load_config(self, config_path: Path):
        with open(config_path, "r", encoding="utf-8") as f:
            configs = json.load(f)

        for cfg in configs["npcs"]:
            memory = MemorySystem(owner=cfg["name"])
            # Load initial memories
            for mem in cfg.get("initial_memories", []):
                memory.store(mem["content"], importance=mem.get("importance", 0.5))

            agent = NPCAgent(
                name=cfg["name"],
                role=cfg["role"],
                personality=cfg["personality"],
                goal=cfg["goal"],
                secret=cfg["secret"],
                memory=memory,
                social_graph=self.social_graph,
            )
            self.agents[cfg["name"]] = agent
            self.npc_descriptions[cfg["name"]] = cfg.get("description", cfg["role"])

        # Load initial relationships
        for rel in configs.get("relationships", []):
            self.social_graph.init_relationship(
                rel["from"], rel["to"],
                trust=rel["trust"], liking=rel["liking"], debt=rel.get("debt", 0.0),
            )

    def _init_relationships(self):
        """Ensure all NPC pairs have a relationship entry."""
        names = list(self.agents.keys())
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                self.social_graph.get(a, b)  # creates default if missing

    async def player_talk(self, npc_name: str, message: str) -> str:
        """Player talks to an NPC."""
        if npc_name not in self.agents:
            return f"这里没有叫{npc_name}的人。"

        if self.game_over:
            return "调查已经结束了。"

        agent = self.agents[npc_name]
        response = await agent.respond(message, speaker="玩家")

        # 埋点：玩家对话 + 话题提取
        try:
            from metrics import get_metrics
            m = get_metrics()
            m.record_player_talk(npc_name)
            topics = [w for w in message.replace("？", "").replace("?", "").split() if len(w) >= 2]
            for t in topics:
                m.record_player_topic(t)

            # 每3次对话抽样检测1次记忆一致性
            total_talks = m.get_total_player_talks()
            if total_talks % 3 == 0:
                await self._check_consistency(agent, response)
        except ImportError:
            pass

        # Advance time slightly
        self.tick_count += 1
        if self.tick_count >= self.ticks_per_day:
            await self._advance_day()

        return response

    async def _advance_day(self):
        """Move to the next day, let NPCs act autonomously."""
        self.tick_count = 0
        self.day += 1

        if self.day > self.max_days:
            self.game_over = True
            try:
                from metrics import get_metrics
                get_metrics().add_path_event("时间耗尽")
            except ImportError:
                pass
            logger.info("Game over: time's up!")
            return

        logger.info("=== 第%d天 ===", self.day)

        # Each NPC takes an autonomous action
        agent_list = list(self.agents.values())
        for agent in agent_list:
            action = await agent.tick(self.day, agent_list)
            if action:
                logger.info("%s 自主行动: %s", agent.name, action)

        # Periodic memory cleanup
        for agent in agent_list:
            agent.memory.forget()

    async def tick_world(self):
        """Manually trigger a world tick (NPC autonomous actions)."""
        agent_list = list(self.agents.values())
        actions = []
        for agent in agent_list:
            action = await agent.tick(self.day, agent_list)
            if action:
                # 埋点：NPC自主行动 + 话题
                try:
                    from metrics import get_metrics
                    m = get_metrics()
                    topic = action.get("content", "")
                    m.record_npc_action(agent.name, topic)
                    # 检测涌现：话题关键词是否在玩家之前的话题中出现过
                    player_topics = m.end_session().player_topics
                    topic_words = set(w for w in topic.replace("？","").replace("?","").split() if len(w) >= 2)
                    if player_topics and not topic_words & player_topics:
                        m.mark_npc_action_emergent(len(m._npc_actions) - 1)
                except ImportError:
                    pass
                actions.append((agent.name, action))

        # 保证至少有一个NPC行动，避免tick完全空转
        if not actions:
            import random as _random
            forced = _random.choice(agent_list)
            action = await forced.tick(self.day, agent_list, force=True)
            if action:
                actions.append((forced.name, action))

        self.tick_count += 1
        if self.tick_count >= self.ticks_per_day:
            await self._advance_day()

        return actions

    async def submit_answer(self, answer: str) -> dict:
        """Player submits their theory. LLM judges correctness."""
        from llm_client import get_llm_client
        llm = get_llm_client()

        judge_prompt = [
            {"role": "system", "content": """你是一个游戏裁判。游戏背景：小镇铁匠声称锤子被偷了，玩家通过与3个NPC对话收集线索，最后提交推理。

你的任务：判断玩家的推理是否正确。

重要规则：
1. 绝对不要直接说出真相或完整事实
2. 如果玩家回答错误，给出模糊的渐进式提示（比如"再想想锤子是不是真的被偷了"或"你可能忽略了某个NPC的动机"）
3. 如果玩家回答正确（核心事实和动机都正确），才判定为correct

用JSON回复：
{"result": "correct"或"partial"或"wrong", "explanation": "对玩家推理的评价（2-3句话，不要透露新信息）", "hint": "如果结果不是correct，给出一个模糊的提示方向，不要直接说出答案"}"""},
            {"role": "user", "content": f"玩家的回答：{answer}"},
        ]

        result = await llm.chat(judge_prompt, json_output=True)
        try:
            parsed = json.loads(result)
            if parsed.get("result") == "correct":
                self.game_over = True
            try:
                from metrics import get_metrics
                m = get_metrics()
                m.record_submission(answer, parsed.get("result", "wrong"))
                if parsed.get("result") == "correct":
                    m.add_path_event("推理正确")
                elif parsed.get("result") == "partial":
                    m.add_path_event("推理部分正确")
                else:
                    m.add_path_event("推理错误")
            except ImportError:
                pass
            return parsed
        except json.JSONDecodeError:
            return {"result": "wrong", "explanation": "无法判定你的回答，请尽量清晰地描述你的推理。", "hint": "想想锤子的去向和铁匠的行为之间有没有矛盾……"}

    async def _check_consistency(self, agent, response: str):
        """抽样检测NPC回复与记忆的一致性，异步调用LLM评判"""
        try:
            from llm_client import get_llm_client
            from metrics import get_metrics
            import json as _json

            recent_memories = agent.memory.get_recent(5)
            if not recent_memories:
                return

            llm = get_llm_client()
            check_prompt = [
                {"role": "system", "content": "你是游戏质量检测员。判断NPC的发言是否与其记忆矛盾。仅回复JSON：{\"contradiction\": true/false}"},
                {"role": "user", "content": f"NPC记忆：\n" + "\n".join(f"- {m}" for m in recent_memories) + f"\n\nNPC发言：{response}\n\n请判断发言是否与记忆矛盾。"},
            ]
            result = await llm.chat(check_prompt, json_output=True)
            parsed = _json.loads(result)
            has_contradiction = parsed.get("contradiction", False)
            get_metrics().record_consistency_check(not has_contradiction)
        except Exception:
            pass  # 检测失败不影响游戏流程

    def get_status(self) -> dict:
        return {
            "day": self.day,
            "max_days": self.max_days,
            "tick": self.tick_count,
            "ticks_per_day": self.ticks_per_day,
            "game_over": self.game_over,
            "relationships": self.social_graph.to_dict(),
        }

    def get_npc_names(self) -> list[str]:
        return list(self.agents.keys())
