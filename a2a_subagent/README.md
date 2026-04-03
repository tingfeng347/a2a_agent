## A2A 主子 Agent 示例

这个示例包含一个主 agent 和两个可独立运行的 subagent：

- `agent_loop.py`：主 agent，启动时自动扫描子 agent 索引，读取各自 `AgentCard/skills` 后再让大模型决定调用谁
- `weather_agent.py`：天气子 agent，负责查询天气
- `news_agent.py`：新闻子 agent，负责查询新闻

主 agent 不直接查天气和新闻，而是通过 A2A 协议把任务转给对应 subagent，拿到结果后再回复用户。
它不会在 prompt 里写死“天气找谁、新闻找谁”，而是根据扫描到的子 agent 能力动态生成工具描述。

### 运行方式

先分别启动两个子 agent：

```bash
uv run weather_agent.py
ur run news_agent.py
```

再启动主 agent：

```bash
uv run agent_loop.py
```

如果你想自定义子 agent 索引，可以在 `.env` 中设置：

```bash
A2A_AGENT_URLS=http://localhost:10002,http://localhost:8005
```

主 agent 启动时会扫描这些地址；运行过程中输入 `refresh` 可以重新扫描索引并刷新工具列表。

### 交互示例

```text
chat> 帮我查一下上海今天天气
chat> 帮我查一下人工智能新闻
chat> 帮我看看北京天气，再给我一条 AI 新闻
```

### 说明

- 天气子 agent 使用 `Open-Meteo` 查询城市天气
- 新闻子 agent 使用 `Google News RSS` 查询新闻
- 如果问题同时涉及多个能力域，主 agent 可以并行调用多个 subagent
- 新增 subagent 时，只要它在索引里且能返回有效 `AgentCard`，主 agent 就能自动发现它的能力
