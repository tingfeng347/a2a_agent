"""物流 Agent：处理轨迹、预计送达、延迟催件，并按需联动规则 Agent。"""

from __future__ import annotations

import asyncio
from typing import override

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
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

from config import LOGISTICS_AGENT_PORT, POLICY_AGENT_URL
from shared.a2a_client import send_text_to_agent
from shared.a2a_server import build_app as build_a2a_app
from shared.debug import debug_log, is_debug_enabled, preview_text
from shared.llm import polish_customer_reply
from shared.service_logic import contains_any, extract_order_id, get_order, logistics_summary


def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="logistics_service",
        name="logistics service agent",
        description="查询物流轨迹、预计送达、催件建议，并处理延迟补偿相关问题",
        tags=["customer-service", "logistics"],
        examples=["A1001物流到哪了", "A1004一直没更新怎么办"],
    )
    return AgentCard(
        name="Logistics Agent",
        description="物流客服Agent",
        url=f"http://localhost:{LOGISTICS_AGENT_PORT}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )


class LogisticsAgentExecutor(AgentExecutor):
    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if not context.message:
            raise Exception("No message provided")

        query = context.get_user_input()
        answer = await self.handle_query(query)

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                context_id=context.context_id,  # type: ignore[arg-type]
                task_id=context.task_id,  # type: ignore[arg-type]
                artifact=new_text_artifact(name="logistics_result", text=answer),
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

    async def handle_query(self, query: str) -> str:
        debug_log("Logistics Agent", f"<= 接到请求 | query={preview_text(query)}")
        order_id = extract_order_id(query)
        if not order_id:
            return "物流Agent需要订单号才能查询轨迹，请提供类似A1001这样的订单号。"

        order = get_order(order_id)
        if not order:
            return f"没有找到订单{order_id}，暂时无法查询物流。"

        sections = [logistics_summary(order_id, order)]
        if contains_any(query, ["赔付", "补偿", "怎么办", "投诉"]):
            sections.append(
                await send_text_to_agent(
                    POLICY_AGENT_URL,
                    query,
                    caller_name="Logistics Agent",
                    target_name="Policy Agent",
                )
            )

        if order["status"] == "delayed":
            sections.append("我建议先登记一次催件工单，并在今日内关注轨迹是否恢复。")
        elif order["status"] == "processing":
            sections.append("订单还未正式出库，当前更适合关注仓库拣货进度。")

        draft = "\n".join(sections)
        return polish_customer_reply(
            system_prompt=(
                "你是一名物流客服。"
                "请把轨迹、预计送达、延迟建议与补偿说明整理成明确的中文答复。"
                "不要捏造，不要使用markdown。"
            ),
            user_prompt=f"用户问题：{query}\n物流答复草稿：\n{draft}",
            fallback=draft,
        )

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")


def build_app():
    return build_a2a_app(build_agent_card(), LogisticsAgentExecutor())


if __name__ == "__main__":
    import uvicorn

    if is_debug_enabled():
        debug_log("Logistics Agent", f"启动调试模式 | listen=http://localhost:{LOGISTICS_AGENT_PORT}")
    uvicorn.run(build_app().build(), host="0.0.0.0", port=LOGISTICS_AGENT_PORT)
