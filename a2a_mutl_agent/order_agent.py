"""订单 Agent：处理订单状态、退款进度，并按需联动物流/规则 Agent。"""

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

from config import LOGISTICS_AGENT_URL, ORDER_AGENT_PORT, POLICY_AGENT_URL
from shared.a2a_client import send_text_to_agent
from shared.a2a_server import build_app as build_a2a_app
from shared.debug import debug_log, is_debug_enabled, preview_text
from shared.llm import polish_customer_reply
from shared.service_logic import contains_any, extract_order_id, format_order_snapshot, get_order, refund_sla_text


def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="order_service",
        name="order service agent",
        description="查询订单状态、付款信息、退款进度，并在需要时联动物流或售后规则 agent",
        tags=["customer-service", "order"],
        examples=["A1002退款什么时候到账", "帮我查A1001订单状态"],
    )
    return AgentCard(
        name="Order Agent",
        description="订单客服Agent",
        url=f"http://localhost:{ORDER_AGENT_PORT}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )


class OrderAgentExecutor(AgentExecutor):
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
                artifact=new_text_artifact(name="order_result", text=answer),
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
        debug_log("Order Agent", f"<= 接到请求 | query={preview_text(query)}")
        order_id = extract_order_id(query)
        if not order_id:
            return "订单Agent需要订单号才能继续处理，请提供类似A1001这样的订单号。"

        order = get_order(order_id)
        if not order:
            return f"没有找到订单{order_id}，请确认订单号是否正确。"

        sections = [format_order_snapshot(order_id, order)]

        if contains_any(query, ["退款", "退货", "多久到账", "售后"]):
            sections.append(refund_sla_text(order))

        tasks: list[asyncio.Task] = []
        if contains_any(query, ["物流", "快递", "到哪", "什么时候到", "催件", "发货", "延迟"]):
            tasks.append(
                asyncio.create_task(
                    send_text_to_agent(
                        LOGISTICS_AGENT_URL,
                        query,
                        caller_name="Order Agent",
                        target_name="Logistics Agent",
                    )
                )
            )
        if contains_any(query, ["退货", "能退吗", "规则", "政策", "赔付", "补偿"]):
            tasks.append(
                asyncio.create_task(
                    send_text_to_agent(
                        POLICY_AGENT_URL,
                        query,
                        caller_name="Order Agent",
                        target_name="Policy Agent",
                    )
                )
            )

        if tasks:
            sections.extend(await asyncio.gather(*tasks))

        draft = "\n".join(sections)
        return polish_customer_reply(
            system_prompt=(
                "你是一名订单客服。"
                "请将订单事实、退款进度和其他agent的补充意见整合成清晰的中文答复。"
                "不要捏造，不要使用markdown。"
            ),
            user_prompt=f"用户问题：{query}\n订单客服草稿：\n{draft}",
            fallback=draft,
        )

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")


def build_app():
    return build_a2a_app(build_agent_card(), OrderAgentExecutor())


if __name__ == "__main__":
    import uvicorn

    if is_debug_enabled():
        debug_log("Order Agent", f"启动调试模式 | listen=http://localhost:{ORDER_AGENT_PORT}")
    uvicorn.run(build_app().build(), host="0.0.0.0", port=ORDER_AGENT_PORT)
