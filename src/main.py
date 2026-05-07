import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")

sys.path.insert(0, str(Path(__file__).parent))

import gradio as gr
import matplotlib.pyplot as plt
import networkx as nx

from world import World

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def create_world() -> World:
    config = Path(__file__).parent.parent / "data" / "npc_configs.json"
    return World(config_path=str(config))


def draw_social_graph(world: World) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(6, 4))
    G = nx.DiGraph()

    names = world.get_npc_names() + ["玩家"]
    for name in names:
        G.add_node(name)

    rel_data = world.social_graph.to_dict()
    for key, vals in rel_data.items():
        a, b = key.split(",")
        liking = vals["liking"]
        if liking > 0:
            G.add_edge(a, b, color="green", weight=liking, label=f"好感{liking:.1f}")
            G.add_edge(b, a, color="green", weight=liking, label="")
        elif liking < 0:
            G.add_edge(a, b, color="red", weight=abs(liking), label=f"好感{liking:.1f}")
            G.add_edge(b, a, color="red", weight=abs(liking), label="")

    pos = nx.spring_layout(G, seed=42)
    edge_colors = [G[u][v].get("color", "gray") for u, v in G.edges()]
    edge_weights = [G[u][v].get("weight", 0.5) * 3 for u, v in G.edges()]

    nx.draw(G, pos, ax=ax, with_labels=True, node_color="lightblue",
            node_size=1500, font_size=12, font_family="SimHei",
            edge_color=edge_colors, width=edge_weights, arrows=True)

    edge_labels = {(u, v): G[u][v]["label"] for u, v in G.edges() if G[u][v].get("label")}
    nx.draw_networkx_edge_labels(G, pos, edge_labels, ax=ax, font_size=8, font_family="SimHei")

    ax.set_title("NPC社交关系图谱", fontsize=14)
    fig.tight_layout()
    return fig


class GameApp:
    def __init__(self):
        self.world = create_world()
        self.game_log: list[str] = [
            "=== 欢迎来到小镇推理 · 失踪的铁锤 ===",
            f"背景：铁匠的锤子被盗了。你有{self.world.max_days}天时间找出真相。",
            "",
            "--- 小镇居民 ---",
        ]
        for name, desc in self.world.npc_descriptions.items():
            self.game_log.append(f"  {name}：{desc}")
        self.game_log.append("")
        self.game_log.append("提示：每个人的记忆和关系都会随对话变化，NPC之间也会自主交流。")
        self.game_log.append("收集足够的线索后，在下方提交你的推理。")
        self.game_log.append("")

        import os as _os
        if not _os.environ.get("OPENAI_API_KEY"):
            self.game_log.append("⚠️ 未检测到 OPENAI_API_KEY 环境变量，NPC 可能无法正常响应。")
            self.game_log.append("   请在终端中设置：set OPENAI_API_KEY=你的API密钥")
            self.game_log.append("")

    def _save_session(self):
        """显示度量报告并持久化到 data/sessions/"""
        try:
            from metrics import get_metrics
            from pathlib import Path as _Path
            import time as _time
            m = get_metrics()
            self.game_log.append(m.format_report())
            session_dir = _Path(__file__).parent.parent / "data" / "sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            ts = int(_time.time())
            m.to_json(session_dir / f"session_{ts}.json")
        except ImportError:
            pass

    def _start_loading(self, message: str = "⏳ NPC 正在思考..."):
        """Show loading state immediately before slow LLM call."""
        log = "\n".join(self.game_log) + f"\n\n{message}"
        return (
            log,
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(),
        )

    def _start_loading_submit(self, message: str = "⏳ 正在判定你的推理..."):
        log = "\n".join(self.game_log) + f"\n\n{message}"
        return (
            log,
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(),
        )

    def _sync_talk(self, npc_name: str, message: str) -> tuple[str, plt.Figure, dict]:
        if self.world.game_over:
            log = "\n".join(self.game_log) + "\n\n调查已经结束。"
            self._save_session()
            log = "\n".join(self.game_log)
            return (log, draw_social_graph(self.world), self.world.get_status(),
                    gr.update(interactive=True), gr.update(interactive=True),
                    gr.update(interactive=True), gr.update(visible=True))

        if not message.strip():
            return ("\n".join(self.game_log), draw_social_graph(self.world), self.world.get_status(),
                    gr.update(interactive=True), gr.update(interactive=True),
                    gr.update(interactive=True), gr.update(visible=self.world.game_over))

        response = asyncio.run(self.world.player_talk(npc_name, message))
        self.game_log.append(f"你对{npc_name}说：{message}")
        self.game_log.append(f"{npc_name}：{response}")
        self.game_log.append(f"[第{self.world.day}天 {self.world.tick_count}/{self.world.ticks_per_day}]")
        self.game_log.append("")

        if self.world.game_over:
            self.game_log.append("\n=== 调查时间已用尽 ===")
            self.game_log.append("你没能找出锤子的真相。也许换一种问法会有不同的结果？")
            self._save_session()

        return ("\n".join(self.game_log), draw_social_graph(self.world), self.world.get_status(),
                gr.update(interactive=True), gr.update(interactive=True),
                gr.update(interactive=True), gr.update(visible=self.world.game_over))

    def _sync_tick(self) -> tuple[str, plt.Figure, dict]:
        if self.world.game_over:
            self._save_session()
            return ("\n".join(self.game_log), draw_social_graph(self.world), self.world.get_status(),
                    gr.update(interactive=True), gr.update(interactive=True),
                    gr.update(interactive=True), gr.update(visible=True))

        actions = asyncio.run(self.world.tick_world())

        if actions:
            for name, action in actions:
                if action.get("action_type") == "talk" and action.get("target"):
                    target = action.get("target", "?")
                    content = action.get("content", "……")
                    target_response = action.get("target_response", "")
                    self.game_log.append(f"[{name}去找了{target}]")
                    self.game_log.append(f"  {name}：{content}")
                    if target_response:
                        self.game_log.append(f"  {target}：{target_response}")
                    event_type = action.get("event_type", "")
                    if event_type:
                        self.game_log.append(f"  （关系变化：{event_type}）")
                else:
                    self.game_log.append(f"[{name}在{action.get('content', '做某事')}]")
            self.game_log.append("")

        self.game_log.append(f"[第{self.world.day}天 {self.world.tick_count}/{self.world.ticks_per_day}]")

        if self.world.game_over:
            self.game_log.append("\n=== 调查时间已用尽 ===")
            self.game_log.append("你没能找出锤子的真相。也许换一种问法会有不同的结果？")
            self._save_session()

        return ("\n".join(self.game_log), draw_social_graph(self.world), self.world.get_status(),
                gr.update(interactive=True), gr.update(interactive=True),
                gr.update(interactive=True), gr.update(visible=self.world.game_over))

    def _sync_submit(self, answer: str) -> tuple[str, plt.Figure, dict, str]:
        if not answer.strip():
            return ("\n".join(self.game_log), draw_social_graph(self.world),
                    self.world.get_status(), "",
                    gr.update(interactive=True), gr.update(interactive=True),
                    gr.update(interactive=True), gr.update(interactive=True),
                    gr.update(visible=self.world.game_over))

        result = asyncio.run(self.world.submit_answer(answer))

        self.game_log.append(f"\n=== 你提交的推理 ===")
        self.game_log.append(answer)

        if result.get("result") == "correct":
            self.game_log.append("\n*** 完全正确！你找出了真相！***")
            self.game_log.append(result.get("explanation", ""))
        elif result.get("result") == "partial":
            self.game_log.append("\n*** 部分正确，但还有关键信息缺失。***")
            self.game_log.append(result.get("explanation", ""))
            self.game_log.append(f"提示：{result.get('hint', '再深入调查一下某个NPC的动机吧。')}")
        else:
            self.game_log.append("\n*** 推理不正确。***")
            self.game_log.append(result.get("explanation", ""))
            self.game_log.append(f"提示：{result.get('hint', '换个角度思考，谁可能有动机说谎？')}")

        result_text = {"correct": "完全正确！", "partial": "部分正确", "wrong": "不正确"}[result.get("result", "wrong")]

        self._save_session()

        return ("\n".join(self.game_log), draw_social_graph(self.world),
                self.world.get_status(), result_text,
                gr.update(interactive=True), gr.update(interactive=True),
                gr.update(interactive=True), gr.update(interactive=True),
                gr.update(visible=self.world.game_over))

    def _reset_game(self):
        """Reset all game state for a new game."""
        self.world = create_world()
        self.game_log = [
            "=== 欢迎来到小镇推理 · 失踪的铁锤 ===",
            f"背景：铁匠的锤子被盗了。你有{self.world.max_days}天时间找出真相。",
            "",
            "--- 小镇居民 ---",
        ]
        for name, desc in self.world.npc_descriptions.items():
            self.game_log.append(f"  {name}：{desc}")
        self.game_log.append("")
        self.game_log.append("提示：每个人的记忆和关系都会随对话变化，NPC之间也会自主交流。")
        self.game_log.append("收集足够的线索后，在下方提交你的推理。")
        self.game_log.append("")

        import os as _os
        if not _os.environ.get("OPENAI_API_KEY"):
            self.game_log.append("⚠️ 未检测到 OPENAI_API_KEY 环境变量，NPC 可能无法正常响应。")
            self.game_log.append("   请在终端中设置：set OPENAI_API_KEY=你的API密钥")
            self.game_log.append("")

        return (
            "\n".join(self.game_log),
            draw_social_graph(self.world),
            self.world.get_status(),
            "",
            gr.update(visible=False),
        )

    def build_ui(self) -> gr.Blocks:
        with gr.Blocks(title="AI NPC 社交推理", theme=gr.themes.Soft()) as demo:
            gr.Markdown("# 🔨 AI NPC 社交推理 · 失踪的铁锤")
            gr.Markdown(f"铁匠的锤子被盗了，你有**{self.world.max_days}天**时间找出真相。和NPC对话收集线索，注意他们之间的关系在动态变化。")

            with gr.Row():
                with gr.Column(scale=2):
                    game_log = gr.Textbox(
                        value="\n".join(self.game_log),
                        label="游戏日志",
                        lines=20,
                        max_lines=40,
                        interactive=False,
                    )
                    with gr.Row():
                        npc_choice = gr.Dropdown(
                            choices=self.world.get_npc_names(),
                            value=self.world.get_npc_names()[0],
                            label="对话对象",
                        )
                        player_input = gr.Textbox(
                            label="你说",
                            placeholder="输入你想说的话...",
                            lines=2,
                        )
                    with gr.Row():
                        talk_btn = gr.Button("💬 对话", variant="primary")
                        tick_btn = gr.Button("⏰ 推进时间", variant="secondary")

                    gr.Markdown("### 📝 提交推理")
                    with gr.Row():
                        answer_input = gr.Textbox(
                            label="你认为锤子到底怎么了？",
                            placeholder="写出你的推理，比如：锤子其实没有被偷，是因为……",
                            lines=3,
                        )
                    with gr.Row():
                        submit_btn = gr.Button("🔍 提交推理", variant="stop")
                        new_game_btn = gr.Button("🔄 开始新游戏", variant="primary", visible=False)
                    result_display = gr.Textbox(label="判定结果", interactive=False)

                with gr.Column(scale=1):
                    graph_output = gr.Plot(label="社交关系图谱")
                    status_display = gr.JSON(label="游戏状态", value=self.world.get_status())

            # Talk button: show loading, then do work
            talk_load = talk_btn.click(
                fn=lambda: self._start_loading("⏳ NPC 正在思考..."),
                outputs=[game_log, talk_btn, tick_btn, player_input, new_game_btn],
                show_progress=False,
            )
            talk_load.then(
                fn=self._sync_talk,
                inputs=[npc_choice, player_input],
                outputs=[game_log, graph_output, status_display,
                         talk_btn, tick_btn, player_input, new_game_btn],
                show_progress=False,
            )

            # Enter key submit: same flow as talk
            input_load = player_input.submit(
                fn=lambda: self._start_loading("⏳ NPC 正在思考..."),
                outputs=[game_log, talk_btn, tick_btn, player_input, new_game_btn],
                show_progress=False,
            )
            input_load.then(
                fn=self._sync_talk,
                inputs=[npc_choice, player_input],
                outputs=[game_log, graph_output, status_display,
                         talk_btn, tick_btn, player_input, new_game_btn],
                show_progress=False,
            )

            # Tick button: show loading, then do work
            tick_load = tick_btn.click(
                fn=lambda: self._start_loading("⏳ NPC 正在行动..."),
                outputs=[game_log, talk_btn, tick_btn, player_input, new_game_btn],
                show_progress=False,
            )
            tick_load.then(
                fn=self._sync_tick,
                outputs=[game_log, graph_output, status_display,
                         talk_btn, tick_btn, player_input, new_game_btn],
                show_progress=False,
            )

            # Submit button: show loading, then do work
            submit_load = submit_btn.click(
                fn=lambda: self._start_loading_submit("⏳ 正在判定你的推理..."),
                outputs=[game_log, talk_btn, tick_btn, submit_btn, answer_input, new_game_btn],
                show_progress=False,
            )
            submit_load.then(
                fn=self._sync_submit,
                inputs=[answer_input],
                outputs=[game_log, graph_output, status_display, result_display,
                         talk_btn, tick_btn, submit_btn, answer_input, new_game_btn],
                show_progress=False,
            )

            # New game button: reset everything
            new_game_btn.click(
                fn=self._reset_game,
                outputs=[game_log, graph_output, status_display, answer_input, new_game_btn],
            )

            demo.load(fn=lambda: draw_social_graph(self.world), outputs=graph_output)

        return demo


if __name__ == "__main__":
    app = GameApp()
    demo = app.build_ui()
    demo.launch(server_name="localhost", server_port=7860)
