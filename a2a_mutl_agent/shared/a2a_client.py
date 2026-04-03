"""A2A 客户端辅助方法。"""

from __future__ import annotations

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory, create_text_message_object
from a2a.types import AgentCard, TransportProtocol
from a2a.utils.message import get_message_text

from .debug import debug_log, preview_text


async def resolve_agent_card(base_url: str) -> AgentCard:
    """读取远端 agent 的 AgentCard。"""
    async with httpx.AsyncClient(timeout=10.0) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
        return await resolver.get_agent_card()


async def send_text_to_agent(
    base_url: str,
    text: str,
    *,
    card: AgentCard | None = None,
    caller_name: str = "Unknown Agent",
    target_name: str | None = None,
) -> str:
    """向远端 agent 发送文本并提取最终文本结果。"""
    async with httpx.AsyncClient(timeout=30.0) as httpx_client:
        resolved_card = card
        if resolved_card is None:
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
            resolved_card = await resolver.get_agent_card()
        resolved_target_name = target_name or resolved_card.name or base_url

        debug_log(
            caller_name,
            f"-> {resolved_target_name} | request={preview_text(text)}",
        )

        config = ClientConfig(
            httpx_client=httpx_client,
            supported_transports=[TransportProtocol.jsonrpc, TransportProtocol.http_json],
            streaming=resolved_card.capabilities.streaming,
        )
        remote_client = ClientFactory(config).create(resolved_card)
        request = create_text_message_object(content=text)

        last_text = ""
        async for response in remote_client.send_message(request):
            task, _ = response
            if not task.artifacts:
                continue
            text_part = get_message_text(task.artifacts[-1]) or ""
            if text_part:
                last_text = text_part

        result = last_text or "对端Agent没有返回内容。"
        debug_log(
            caller_name,
            f"<- {resolved_target_name} | response={preview_text(result)}",
        )
        return result
