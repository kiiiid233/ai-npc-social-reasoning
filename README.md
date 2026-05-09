# AI NPC 社交推理 · 失踪的铁锤

多Agent NPC社交推理原型——探索LLM与Agent技术在游戏设计中的融合。

## 项目定位

一款探索“AI+游戏设计”跨界融合的作品集项目，旨在展示从底层大模型调用、Agent架构设计到上层玩法逻辑闭环的综合落地能力：

- **Agent设计**：3个拥有独立目标、性格、记忆的NPC Agent，可自主行动与交互
- **知识工程**：基于ChromaDB向量数据库的NPC记忆系统，支持语义检索与艾宾浩斯遗忘曲线时间衰减
- **容错机制**：LLM调用重试、JSON格式校验、超时降级
- **体验度量**：完整的游戏内指标采集、报告展示与跨局分析工具

## 场景简介

中世纪小镇，铁匠的锤子"被盗"。玩家有3天时间通过对3个NPC的对话调查真相。

3个NPC各怀秘密，关系动态变化，NPC之间会自主交流——每次游玩路径不同。

## 快速开始

```cmd
pip install -r requirements.txt

:: 设置OpenAI API Key（使用DeepSeek API）
set OPENAI_API_KEY=your-key-here

:: 启动
cd src
python main.py
```

浏览器打开 http://localhost:7860 即可游玩。

## 技术架构

```
玩家输入 → GameApp (Gradio) → World
               ↓
           NPC Agent (×3)
           ├── 记忆系统 (ChromaDB + 遗忘曲线)
           ├── 社交关系图谱 (信任/好感/亏欠)
           └── LLM (DeepSeek-V4-Flash)
               ↓
           MetricsTracker → 度量报告 + JSON持久化
```

- **LLM**: DeepSeek-V4-Flash（低成本，足够驱动NPC对话与决策）
- **向量数据库**: ChromaDB（本地运行，零配置）
- **Agent框架**: 手写（展示对Agent机制的深入理解）
- **前端**: Gradio（快速搭出可交互界面）
- **度量**: 内建MetricsTracker（延迟/一致性/涌现/路径四项指标）

## 核心设计

### 记忆系统
- 语义检索：基于ChromaDB的向量相似度搜索
- 时间衰减：仿照艾宾浩斯遗忘曲线，重要性×(0.5^(小时/24))
- 主动遗忘：低于阈值的记忆被自动清理

### Agent自主行动
- 每个时间步，NPC有70%概率主动行动（至少保证1个NPC行动）
- NPC可主动和其他NPC对话或独自做事
- NPC间对话会触发目标NPC的真实LLM回复，更新双方记忆和关系图谱
- 涌现性：信息在社交网络中传播，玩家未触发的对话也能改变局势

### 容错机制
| 故障类型 | 处理策略 |
|---------|---------|
| LLM返回非JSON | 重试并在Prompt中强调格式要求 |
| 连续格式错误 | 降级返回预设保守回复 |
| API超时 | 跳过本轮Agent行动 |

### 体验度量系统

游戏内建度量采集，游戏结束时自动展示报告并写入 `data/sessions/`。

| 指标 | 度量方式 | 目标值 |
|------|---------|--------|
| 响应延迟 | 每次LLM调用计时，统计avg/min/max/P50/P99 | < 3秒 |
| 记忆一致性 | 每3次对话抽样，LLM评判回复是否与记忆矛盾 | 矛盾率 < 15% |
| 社交涌现性 | NPC自主对话话题 vs 玩家已触及话题对比 | 涌现率 > 30% |
| 路径多样性 | 记录每局关键事件序列，跨局对比 | ≥ 3条不同路径 |

跨局路径对比：
```bash
python scripts/compare_paths.py
```

## 项目结构

```
ai-npc-social-reasoning/
├── src/
│   ├── main.py          # Gradio界面入口 + 度量报告展示
│   ├── agent.py         # NPC Agent类
│   ├── memory.py        # 记忆系统（ChromaDB + 遗忘曲线）
│   ├── social_graph.py  # 社交关系图谱
│   ├── llm_client.py    # LLM调用封装（含容错+延迟计时）
│   ├── world.py         # 游戏世界状态管理 + 一致性检测
│   ├── metrics.py       # 度量采集、统计、报告、持久化
│   └── prompts/
│       ├── npc_system.txt  # NPC对话System Prompt
│       └── npc_tick.txt    # NPC自主行动Prompt
├── data/
│   ├── npc_configs.json    # NPC初始配置
│   └── sessions/           # 每局度量JSON记录
├── scripts/
│   └── compare_paths.py    # 跨局路径多样性对比
├── docs/
│   ├── ai-design-notes.md  # AI+游戏设计说明
│   └── superpowers/        # 设计文档与实现计划
└── requirements.txt
```
