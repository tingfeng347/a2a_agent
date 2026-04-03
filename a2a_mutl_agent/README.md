## A2A 客服多智能体示例

这个目录展示了一个通过 A2A 协议通信的客服多智能体系统，核心特点是多个平级 agent 之间可以互相协作，而不是只有单一主从调用。

### 角色说明

- `triage_agent.py`：客服接待 agent，负责识别问题并协调其他 agent。
- `order_agent.py`：订单 agent，处理订单状态、退款进度，并按需联动物流或规则 agent。
- `policy_agent.py`：规则 agent，解释退货退款、延迟补偿等售后政策。
- `logistics_agent.py`：物流 agent，处理轨迹、预计送达、催件建议，并按需联动规则 agent。
- `customer_console.py`：命令行入口，模拟用户向客服系统提问。

### 协作方式

- 用户先向 `triage_agent` 发起咨询。
- `triage_agent` 会根据问题内容调用一个或多个平级 agent。
- `order_agent` 在处理退款、退货、物流混合问题时，也会继续调用 `policy_agent` 或 `logistics_agent`。
- `logistics_agent` 遇到补偿、赔付类问题时，会继续调用 `policy_agent`。

这意味着这里不是单层主从结构，而是多个 agent 之间可以横向协作。

### 运行方式

最简单的方式是一键启动：

```bash
uv run run_demo.py
```

如果你想看 agent 间调用方向：

```bash
uv run run_demo.py --debug
```

它会自动拉起 4 个 agent，然后直接进入客服控制台；退出控制台时也会自动回收本次启动的 agent 进程。

如果你想分别观察每个进程，也可以打开 5 个终端，在 `a2a_mutl_agent` 目录下分别运行：

```bash
uv run triage_agent.py
uv run order_agent.py
uv run policy_agent.py
uv run logistics_agent.py
uv run customer_console.py
```

如果你想观察 agent 之间的调用方向和协作流程，可以给每个进程都加上 `--debug`：

```bash
uv run triage_agent.py --debug
uv run order_agent.py --debug
uv run policy_agent.py --debug
uv run logistics_agent.py --debug
uv run customer_console.py --debug
```

开启后会打印类似下面的调试链路：

```text
[DEBUG][Customer Console] -> Triage Agent | request=A1004延迟了可以补偿吗
[DEBUG][Triage Agent] -> Order Agent | request=A1004延迟了可以补偿吗
[DEBUG][Triage Agent] -> Logistics Agent | request=A1004延迟了可以补偿吗
[DEBUG][Logistics Agent] -> Policy Agent | request=A1004延迟了可以补偿吗
```

### 可测试问题

```text
A1001到哪了
A1002退款什么时候到账
A1002还能退货吗
A1004延迟了可以补偿吗
A1001什么时候到，能不能催一下
```

### 说明

- 数据是本地 mock 数据，定义在 `shared/mock_data.py`。
- A2A 客户端与服务端辅助代码在 `shared/a2a_client.py` 和 `shared/a2a_server.py`。
- 如果根目录 `.env` 里配置了 `OPENAI_MODEL`、`OPENAI_BASE_URL`、`OPENAI_API_KEY`，各 agent 会自动用大模型把草稿润色成更自然的客服回复；没有也能运行。
