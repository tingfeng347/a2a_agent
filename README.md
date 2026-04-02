## A2A 主子 Agent 示例

这个示例包含一个主 agent 和两个可独立运行的 subagent：

- `agent_loop.py`：主 agent，使用大模型决定是否调用子 agent
- `weather_agent.py`：天气子 agent，负责查询天气
- `news_agent.py`：新闻子 agent，负责查询新闻

主 agent 不直接查天气和新闻，而是通过 A2A 协议把任务转给对应 subagent，拿到结果后再回复用户。

### 运行方式

先分别启动两个子 agent：

```bash
.venv\Scripts\python.exe weather_agent.py
.venv\Scripts\python.exe news_agent.py
```

再启动主 agent：

```bash
.venv\Scripts\python.exe agent_loop.py
```

### 交互示例

```text
chat> 帮我查一下上海今天天气
chat> 帮我查一下人工智能新闻
chat> 帮我看看北京天气，再给我一条 AI 新闻
```

### 说明

- 天气子 agent 使用 `Open-Meteo` 查询城市天气
- 新闻子 agent 使用 `Google News RSS` 查询新闻
- 如果问题同时涉及天气和新闻，主 agent 可以连续调用多个 subagent
