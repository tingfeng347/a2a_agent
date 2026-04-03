import os
import re
import xml.etree.ElementTree as ET
from typing import override
from urllib.parse import quote_plus

import httpx
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils import new_text_artifact
from openai import OpenAI
import dotenv

dotenv.load_dotenv()

SUBAGENT_MODEL = os.getenv("SUBAGENT_MODEL")
SUBAGENT_BASE_URL = os.getenv("SUBAGENT_BASE_URL")
SUBAGENT_API_KEY = os.getenv("SUBAGENT_API_KEY")

# 新闻子 agent 内部用于摘要整理的大模型客户端。
llm_client = OpenAI(base_url=SUBAGENT_BASE_URL, api_key=SUBAGENT_API_KEY)


def extract_topic(query: str) -> str:
    # 从用户问题里提取新闻检索主题，提取失败时回退到默认热点。
    cleaned = re.sub(r"(帮我|请|一下|看看|查询|搜索|最近|最新|新闻|资讯|热点|消息|查|查下|查一下)", " ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "今日热点"


def polish_news_result_with_llm(topic: str, raw_result: str) -> str:
    # 对 RSS 原始新闻列表做二次整理，生成更适合阅读的中文摘要。
    try:
        response = llm_client.chat.completions.create(
            model=SUBAGENT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是新闻摘要助手。"
                        "根据原始新闻列表，输出更易读的中文摘要。"
                        "输出要求："
                        "1. 只输出中文纯文本；"
                        "2. 先给一段2-3句的整体趋势总结；"
                        "3. 再列出最多5条新闻，每条包含标题和一句亮点；"
                        "4. 不要捏造原始列表中没有的信息；"
                        "5. 不要使用 markdown。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"主题：{topic}\n原始新闻：\n{raw_result}",
                },
            ],
            extra_body={"enable_thinking": False},
        )
        content = response.choices[0].message.content
        if content:
            return f"新闻子Agent结果：{content.strip()}"
    except Exception:
        pass

    return raw_result


async def query_news(topic: str) -> str:
    # 使用 Google News RSS 拉取指定主题的新闻列表。
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(topic)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        xml_text = response.text

    root = ET.fromstring(xml_text)
    items = root.findall("./channel/item")
    if not items:
        return f"新闻子Agent没有找到与“{topic}”相关的新闻。"

    lines = [f"新闻Agent结果：与“{topic}”相关的新闻如下："]
    for index, item in enumerate(items[:5], start=1):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        lines.append(f"{index}. {title} | {pub_date} | {link}")

    raw_result = "\n".join(lines)
    return polish_news_result_with_llm(topic, raw_result)


class NewsAgentExecutor(AgentExecutor):
    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # A2A 执行入口：提取主题、检索新闻，再把结果写回事件流。
        if not context.message:
            raise Exception("No message provided")

        query = context.get_user_input()
        topic = extract_topic(query)

        try:
            answer = await query_news(topic)
        except Exception as exc:
            answer = f"新闻子Agent查询失败：{exc}"

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                context_id=context.context_id,  # type: ignore[arg-type]
                task_id=context.task_id,  # type: ignore[arg-type]
                artifact=new_text_artifact(name="news_result", text=answer),
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                context_id=context.context_id,  # type: ignore[arg-type]
                task_id=context.task_id,  # type: ignore[arg-type]
                status=TaskStatus(state=TaskState.completed),
                final=True,
            )
        )

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")


def build_app() -> A2AStarletteApplication:
    # 暴露标准 AgentCard，供主 agent 启动时自动发现新闻能力。
    skill = AgentSkill(
        id="news_query",
        name="news query agent",
        description="查询新闻热点并返回标题与链接",
        tags=["news", "search"],
        examples=["帮我查一下人工智能新闻"],
    )
    agent_card = AgentCard(
        name="News Agent",
        description="新闻子Agent",
        url="http://localhost:10003/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )
    handler = DefaultRequestHandler(
        agent_executor=NewsAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )
    return A2AStarletteApplication(agent_card=agent_card, http_handler=handler)


if __name__ == "__main__":
    import uvicorn

    # 直接运行当前文件时，启动本地新闻子 agent 服务。
    uvicorn.run(build_app().build(), host="0.0.0.0", port=10003)
