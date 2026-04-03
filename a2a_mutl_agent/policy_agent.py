"""规则 Agent：解释退货、退款、延迟补偿等售后规则。"""

from __future__ import annotations

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

from config import POLICY_AGENT_PORT
from shared.a2a_server import build_app as build_a2a_app
from shared.debug import debug_log, is_debug_enabled, preview_text
from shared.llm import polish_customer_reply
from shared.service_logic import evaluate_return_eligibility, extract_order_id, get_order, policy_summary


def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="policy_service",
        name="policy service agent",
        description="回答退货退款、延迟补偿、售后条件等规则问题",
        tags=["customer-service", "policy"],
        examples=["A1004延迟了可以补偿吗", "智能手表拆封后还能退吗"],
    )
    return AgentCard(
        name="Policy Agent",
        description="售后规则Agent",
        url=f"http://localhost:{POLICY_AGENT_PORT}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )


class PolicyAgentExecutor(AgentExecutor):
    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if not context.message:
            raise Exception("No message provided")

        query = context.get_user_input()
        answer = self.handle_query(query)

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                context_id=context.context_id,  # type: ignore[arg-type]
                task_id=context.task_id,  # type: ignore[arg-type]
                artifact=new_text_artifact(name="policy_result", text=answer),
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

    def handle_query(self, query: str) -> str:
        debug_log("Policy Agent", f"<= 接到请求 | query={preview_text(query)}")
        order_id = extract_order_id(query)
        base = policy_summary()

        if order_id:
            order = get_order(order_id)
            if not order:
                return f"规则Agent没有找到订单{order_id}，当前只能先提供通用规则：{base}"

            draft = (
                f"{base}\n"
                f"结合订单{order_id}来看：{evaluate_return_eligibility(order)} "
                f"当前退款状态：{order['refund_status']}。"
            )
        else:
            draft = base

        return polish_customer_reply(
            system_prompt=(
                "你是一名售后规则客服。"
                "请把售后规则解释得清楚、克制、可执行。"
                "不要捏造，不要使用markdown。"
            ),
            user_prompt=f"用户问题：{query}\n规则答复草稿：\n{draft}",
            fallback=draft,
        )

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")


def build_app():
    return build_a2a_app(build_agent_card(), PolicyAgentExecutor())


if __name__ == "__main__":
    import uvicorn

    if is_debug_enabled():
        debug_log("Policy Agent", f"启动调试模式 | listen=http://localhost:{POLICY_AGENT_PORT}")
    uvicorn.run(build_app().build(), host="0.0.0.0", port=POLICY_AGENT_PORT)
