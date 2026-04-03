import asyncio
import json
import locale
import platform
import re
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Any

import dotenv
import httpx
from a2a.client import (
    A2ACardResolver,
    ClientConfig,
    ClientFactory,
    create_text_message_object,
)
from a2a.types import AgentCard
from a2a.types import TransportProtocol
from a2a.utils.message import get_message_text
from openai import OpenAI
dotenv.load_dotenv()
import os

# 主 agent 使用的大模型客户端。
client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
)

@dataclass
class DiscoveredAgent:
    # tool_name 是暴露给大模型的工具名，base_url 是实际调用地址。
    tool_name: str
    base_url: str
    card: AgentCard
    description: str


def parse_subagent_index() -> list[str]:
    # 支持通过环境变量覆盖默认索引，便于后续扩展更多子 agent。
    raw = os.getenv("A2A_AGENT_URLS", "")
    urls = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    return urls 


def slugify_tool_name(value: str) -> str:
    # 将字符串转换成 function calling 可接受的稳定工具名。
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    if not slug:
        slug = "subagent"
    if slug[0].isdigit():
        slug = f"subagent_{slug}"
    return slug


def make_tool_name(card: AgentCard, base_url: str) -> str:
    # 优先用 skill.id 命名，确保工具名尽可能稳定、可读。
    for skill in card.skills or []:
        if skill.id:
            return slugify_tool_name(skill.id)
    if card.name:
        return slugify_tool_name(card.name)
    host = urlparse(base_url).netloc or base_url
    return slugify_tool_name(host)


def build_agent_description(card: AgentCard) -> str:
    # 将 AgentCard 中的描述、标签和示例整理成提示词可直接使用的能力摘要。
    parts = [card.description or f"{card.name} 提供的能力"]
    for skill in card.skills or []:
        segment = skill.description or skill.name or skill.id
        extras = []
        if skill.tags:
            extras.append("标签：" + "、".join(skill.tags[:5]))
        if skill.examples:
            extras.append("示例：" + "；".join(skill.examples[:2]))
        if extras:
            segment = f"{segment}（{'；'.join(extras)}）"
        parts.append(segment)
    return " ".join(part.strip() for part in parts if part and part.strip())


async def discover_subagents() -> dict[str, DiscoveredAgent]:
    # 启动时扫描所有子 agent，并读取各自的 AgentCard 建立运行时索引。
    discovered: dict[str, DiscoveredAgent] = {}
    async with httpx.AsyncClient(timeout=10.0) as httpx_client:
        for base_url in parse_subagent_index():
            try:
                resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
                card = await resolver.get_agent_card()
            except Exception as exc:
                print(f"[discover] 跳过 {base_url}，读取 AgentCard 失败：{exc}")
                continue

            tool_name = make_tool_name(card, base_url)
            while tool_name in discovered:
                tool_name = f"{tool_name}_dup"

            discovered[tool_name] = DiscoveredAgent(
                tool_name=tool_name,
                base_url=base_url,
                card=card,
                description=build_agent_description(card),
            )
    return discovered


def build_system_prompt(agents: dict[str, DiscoveredAgent]) -> str:
    # 根据扫描结果动态生成系统提示，避免在 prompt 里写死子 agent 能力。
    agent_lines = []
    for item in agents.values():
        skill_names = ", ".join(
            skill.name or skill.id for skill in (item.card.skills or []) if (skill.name or skill.id)
        )
        suffix = f" 技能：{skill_names}。" if skill_names else ""
        agent_lines.append(f"- {item.tool_name}：{item.description}{suffix}")

    agent_block = "\n".join(agent_lines) if agent_lines else "- 当前没有可用子Agent。"

    return f"""你是 MagicCode，一名能够自主编排子Agent的终端 AI 助手，回复尽量简洁有说服力。

## 你的工具
- bash：执行本机 shell 命令，适合文件操作、环境检查、代码搜索。
{agent_block}

## 调用规则
1. 先根据工具描述和子Agent技能，自主判断应该调用哪个子Agent，不要依赖固定映射。
2. 如果用户问题命中某个子Agent的能力，优先调用对应子Agent；仅当没有合适子Agent时再考虑 bash。
3. 同一个问题如果涉及多个能力域，可以在同一轮并行调用多个子Agent，再整合结果回复。
4. 在拿到子Agent结果后，再面向用户给出最终答复。

## 严格遵守
1. 将复杂任务拆分为多个步骤，并逐步验证。
2. 禁止执行破坏性命令。
3. 只输出纯文本，不要任何 markdown 语法。
4. 输出内容必须是中文。
"""


def build_tools(agents: dict[str, DiscoveredAgent]) -> list[dict[str, Any]]:
    # 先保留 bash，再把动态发现的子 agent 全部注册成工具。
    tools = [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Run a shell command.",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        }
    ]

    for item in agents.values():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": item.tool_name,
                    "description": item.description,
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        )
    return tools


def run_bash(command: str, timeout: int = 10) -> str:
    # 提供一个兜底 shell 工具，处理本地搜索、环境检查等任务。
    try:
        if platform.system().lower().startswith("win"):
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
        else:
            proc = subprocess.run(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                encoding=locale.getpreferredencoding(False),
                errors="replace",
            )
        return proc.stdout or ""
    except Exception as e:
        return f"Error running command: {e}"


async def call_a2a_agent(base_url: str, query: str) -> str:
    # 通过 A2A 协议向子 agent 发送请求，并提取最终文本结果。
    async with httpx.AsyncClient(timeout=30.0) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
        card = await resolver.get_agent_card()
        config = ClientConfig(
            httpx_client=httpx_client,
            supported_transports=[
                TransportProtocol.jsonrpc,
                TransportProtocol.http_json,
            ],
            streaming=card.capabilities.streaming,
        )
        remote_client = ClientFactory(config).create(card)
        request = create_text_message_object(content=query)

        last_text = ""
        async for response in remote_client.send_message(request):
            task, _ = response
            if not task.artifacts:
                continue
            text = get_message_text(task.artifacts[-1]) or ""
            if text:
                last_text = text

        return last_text or "子Agent没有返回内容。"


async def handle_bash(arguments: dict[str, Any]) -> str:
    # 将阻塞式 shell 调用放到线程池执行，避免卡住事件循环。
    return await asyncio.to_thread(run_bash, arguments.get("command", ""))


def sanitize_text(text: str) -> str:
    # 统一做一次编码清洗，减少终端输出乱码的概率。
    return text.encode("utf-8", errors="replace").decode("utf-8")


def print_discovered_agents(agents: dict[str, DiscoveredAgent], title: str) -> None:
    # 启动和刷新时打印当前发现到的子 agent，方便观察索引状态。
    print(title)
    if not agents:
        print("- 当前没有扫描到可用子Agent")
        return

    for item in agents.values():
        print(f"URL:{item.base_url}")
        print(f"名称: {item.card.name}")
        print(f"能力: {item.description}")


class MagicCode:
    def __init__(self):
        # 初始化时先扫描子 agent，再据此生成 prompt、tools 和会话历史。
        self.discovered_agents = asyncio.run(discover_subagents())
        self.system_prompt = build_system_prompt(self.discovered_agents)
        self.tools = build_tools(self.discovered_agents)
        self.history = [{"role": "system", "content": self.system_prompt}]
        print_discovered_agents(self.discovered_agents, "[discover] 扫描agent结果")

    def reset_history(self):
        self.history = [{"role": "system", "content": self.system_prompt}]

    async def refresh_subagents(self):
        # refresh 命令会重新扫描索引，并重建工具和系统提示。
        self.discovered_agents = await discover_subagents()
        self.system_prompt = build_system_prompt(self.discovered_agents)
        self.tools = build_tools(self.discovered_agents)
        self.reset_history()
        print_discovered_agents(self.discovered_agents, "[discover] 刷新扫描结果")

    async def handle_subagent(self, tool_name: str, arguments: dict[str, Any]) -> str:
        # 将模型选中的工具名映射回子 agent 地址，再转发 query。
        agent = self.discovered_agents.get(tool_name)
        if not agent:
            return f"未找到名为 {tool_name} 的子Agent。"
        return await call_a2a_agent(agent.base_url, arguments.get("query", ""))

    def think_first(self, user_input: str) -> str:
        # 先做一轮轻量意图规划，便于在终端里看到主 agent 的下一步动作。
        safe_input = sanitize_text(user_input)
        tool_names = ", ".join(self.discovered_agents.keys()) or "无可用子Agent"
        think_messages = self.history + [
            {"role": "user", "content": safe_input},
            {
                "role": "system",
                "content": (
                    "模拟人类的思考过程，简短有力，最多25字，规划下一步要做什么。"
                    "要求："
                    "1. 输出内容必须是中文，且只包含对当前用户输入的理解与下一步意图；"
                    "2. 必须明确写出“无需调用工具”或“需要调用什么工具”；"
                    f"3. 如需调用子Agent，只能从这些工具里选择：{tool_names}；"
                    "4. 不要分点，不要编号，不要 markdown；"
                    "5. 不要直接给最终回答内容；"
                    "6. 不要输出多余解释。"
                ),
            },
        ]

        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL"),
            messages=think_messages,
            extra_body={"enable_thinking": False},
        )
        msg = response.choices[0].message
        if not msg.content:
            return "用户意图不明确，无法判断是否需要调用工具。"
        return sanitize_text(msg.content.strip())

    async def _run_single_tool_call(self, tc, tool_count: int) -> dict[str, str | int]:
        # 封装单次工具调用，便于后续并行执行多个 tool call。
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        info = json.dumps(args, ensure_ascii=False)
        if len(info) > 160:
            info = info[:160] + "..."

        print(f"[{tool_count}] Act: 调用工具 {name} {info}")

        if name == "bash":
            result = await handle_bash(args)
        else:
            result = await self.handle_subagent(name, args)
        result = sanitize_text(result)

        return {
            "tool_call_id": tc.id,
            "result": result,
            "tool_count": tool_count,
        }

    async def chat(self, user_input: str):
        # 单轮对话可能包含多次工具调用，直到模型给出最终回复为止。
        tool_count = 0
        safe_input = sanitize_text(user_input)

        think_text = self.think_first(safe_input)
        print(f"Think: {think_text}")

        self.history.append({"role": "user", "content": safe_input})
        self.history.append({"role": "assistant", "content": f"{think_text}"})

        while True:
            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL"),
                messages=self.history,
                tools=self.tools,
                parallel_tool_calls=True,
                extra_body={"enable_thinking": False},
            )

            message = response.choices[0].message
            self.history.append(message.model_dump(exclude_none=True))

            if message.content:
                print(f"Result: {sanitize_text(message.content.strip())}")

            if not message.tool_calls:
                break

            tasks = []
            for tc in message.tool_calls:
                tool_count += 1
                tasks.append(self._run_single_tool_call(tc, tool_count))

            tool_results = await asyncio.gather(*tasks)

            for item in tool_results:
                n = item["tool_count"]
                result = item["result"]
                print(f"[{n}] Obs: {result.strip() or '(无输出)'}")

                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": item["tool_call_id"],
                        "content": result,
                    }
                )

            if tool_count > 20:
                print("Tool call limit reached (20)")
                break

    def run(self):
        # 命令行主循环，支持 exit / clear / refresh 三个控制命令。
        while True:
            try:
                user_input = input("chat> ").strip()
                if not user_input:
                    continue

                cmd = user_input.lower()
                if cmd in ("exit", "quit"):
                    break
                if cmd == "clear":
                    self.reset_history()
                    print("历史已清空")
                    continue
                if cmd == "refresh":
                    asyncio.run(self.refresh_subagents())
                    continue

                asyncio.run(self.chat(user_input))
                print()

            except KeyboardInterrupt:
                print("\n再见！")
                break


if __name__ == "__main__":
    MagicCode().run()
