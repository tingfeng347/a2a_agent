import asyncio
import json
import locale
import platform
import subprocess

import dotenv
import httpx
from a2a.client import (
    A2ACardResolver,
    ClientConfig,
    ClientFactory,
    create_text_message_object,
)
from a2a.types import TransportProtocol
from a2a.utils.message import get_message_text
from openai import OpenAI

dotenv.load_dotenv()

MODEL = "qwen3.5-27b"
WEATHER_AGENT_BASE_URL = "http://localhost:10002"
NEWS_AGENT_BASE_URL = "http://localhost:10003"

client = OpenAI(
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key="sk-c0984e52de364cd7aea86f5c7172f3b6",
)

SYSTEM_PROMPT = """你是 MagicCode，一名能够自主编排子Agent的终端 AI 助手，回复尽量简洁有说服力。

## 你的工具
- bash：执行本机 shell 命令，适合文件操作、环境检查、代码搜索。
- ask_weather_agent：通过 A2A 协议把天气相关任务交给天气子Agent。
- ask_news_agent：通过 A2A 协议把新闻相关任务交给新闻子Agent。

## 调用规则
1. 用户的问题涉及天气、气温、降雨、穿衣建议、出行天气时，优先调用 ask_weather_agent。
2. 用户的问题涉及新闻、热点、最近发生了什么、某个主题的资讯时，优先调用 ask_news_agent。
3. 同一个问题如果同时涉及天气和新闻，可以连续调用多个子Agent，再整合结果回复。
4. 不要为了查询天气或新闻去调用 bash，优先使用对应子Agent。

## 严格遵守
1. 将复杂任务拆分为多个步骤，并逐步验证。
2. 禁止执行破坏性命令。
3. 只输出纯文本，不要任何 markdown 语法。
4. 输出内容必须是中文。
5. 在拿到子Agent结果后，再面向用户给出最终答复。
"""

TOOLS = [
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
    },
    {
        "type": "function",
        "function": {
            "name": "ask_weather_agent",
            "description": "通过 A2A 协议调用天气子Agent，查询天气、温度、降雨和出行建议。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_news_agent",
            "description": "通过 A2A 协议调用新闻子Agent，查询实时新闻、热点和某个主题的资讯。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def run_bash(command: str, timeout: int = 10) -> str:
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


def ask_weather_agent(query: str) -> str:
    return asyncio.run(call_a2a_agent(WEATHER_AGENT_BASE_URL, query))


def ask_news_agent(query: str) -> str:
    return asyncio.run(call_a2a_agent(NEWS_AGENT_BASE_URL, query))


TOOL_HANDLERS = {
    "bash": lambda arguments: run_bash(arguments.get("command", "")),
    "ask_weather_agent": lambda arguments: ask_weather_agent(arguments.get("query", "")),
    "ask_news_agent": lambda arguments: ask_news_agent(arguments.get("query", "")),
}


def sanitize_text(text: str) -> str:
    return text.encode("utf-8", errors="replace").decode("utf-8")


class MagicCode:
    def __init__(self):
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def think_first(self, user_input: str) -> str:
        safe_input = sanitize_text(user_input)
        think_messages = self.history + [
            {"role": "user", "content": safe_input},
            {
                "role": "system",
                "content": (
                    "模拟人类的思考过程，规划下一步要做什么。"
                    "要求："
                    "1. 输出内容必须是中文，且只包含对当前用户输入的理解与下一步意图；"
                    "2. 必须明确写出“无需调用工具”或“需要调用什么工具”；"
                    "3. 如果是天气问题要写 ask_weather_agent，如果是新闻问题要写 ask_news_agent；"
                    "4. 不要分点，不要编号，不要 markdown；"
                    "5. 不要直接给最终回答内容；"
                    "6. 不要输出多余解释。"
                ),
            },
        ]

        response = client.chat.completions.create(
            model=MODEL,
            messages=think_messages,
            extra_body={"enable_thinking": False},
        )
        msg = response.choices[0].message
        if not msg.content:
            return "用户意图不明确，无法判断是否需要调用工具。"
        return sanitize_text(msg.content.strip())

    def chat(self, user_input: str):
        tool_count = 0
        safe_input = sanitize_text(user_input)

        think_text = self.think_first(safe_input)
        print(f"Think: {think_text}")

        self.history.append({"role": "user", "content": safe_input})
        self.history.append({"role": "assistant", "content": f"{think_text}"})

        while True:
            response = client.chat.completions.create(
                model=MODEL,
                messages=self.history,
                tools=TOOLS,
                extra_body={"enable_thinking": False},
            )

            message = response.choices[0].message
            self.history.append(message.model_dump(exclude_none=True))

            if message.content:
                print(f"Result: {sanitize_text(message.content.strip())}")

            if not message.tool_calls:
                break

            for tc in message.tool_calls:
                tool_count += 1
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                info = json.dumps(args, ensure_ascii=False)
                if len(info) > 160:
                    info = info[:160] + "..."

                print(f"[{tool_count}] Act: 调用工具 {name} {info}")

                handler = TOOL_HANDLERS.get(name)
                result = handler(args) if handler else f"Unknown tool: {name}"
                result = sanitize_text(result)

                print(f"[{tool_count}] Obs: {result.strip() or '(无输出)'}")

                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )

            if tool_count > 20:
                print("Tool call limit reached (20)")
                break

    def run(self):
        while True:
            try:
                user_input = input("chat> ").strip()
                if not user_input:
                    continue

                cmd = user_input.lower()
                if cmd in ("exit", "quit"):
                    break
                if cmd == "clear":
                    self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
                    print("历史已清空")
                    continue

                self.chat(user_input)
                print()

            except KeyboardInterrupt:
                print("\n再见！")
                break


if __name__ == "__main__":
    MagicCode().run()
