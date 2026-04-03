"""客服接待 Agent：识别用户问题并协调平级客服 agent。"""

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

from config import LOGISTICS_AGENT_URL, ORDER_AGENT_URL, POLICY_AGENT_URL, TRIAGE_AGENT_PORT
from shared.a2a_client import send_text_to_agent
from shared.a2a_server import build_app as build_a2a_app
from shared.debug import debug_log, is_debug_enabled, preview_text
from shared.llm import polish_customer_reply
from shared.service_logic import contains_any, extract_order_id


def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="customer_service_triage",
        name="customer service triage",
        description="识别客服问题意图，并协调订单、物流、售后规则 agent 给出统一答复",
        tags=["customer-service", "triage"],
        examples=["订单A1001到哪了，能不能催一下", "A1002退款什么时候到账"],
    )
    return AgentCard(
        name="Triage Agent",
        description="客服接待与协同Agent",
        url=f"http://localhost:{TRIAGE_AGENT_PORT}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )


class TriageAgentExecutor(AgentExecutor):
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
                artifact=new_text_artifact(name="triage_result", text=answer),
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
        debug_log("Triage Agent", f"<= 用户请求 | query={preview_text(query)}")
        order_id = extract_order_id(query)
        needs_order = bool(order_id) or contains_any(query, ["订单", "退款", "退货", "支付", "状态"])
        needs_logistics = contains_any(query, ["物流", "快递", "催件", "到哪", "发货", "什么时候到", "轨迹", "延迟"])
        needs_policy = contains_any(query, ["规则", "政策", "能退吗", "可以退吗", "赔付", "补偿", "售后", "退款多久到账"])

        debug_log(
            "Triage Agent",
            f"路由判断 | order={needs_order}, logistics={needs_logistics}, policy={needs_policy}, order_id={order_id or '无'}",
        )

        tasks: list[tuple[str, asyncio.Future | asyncio.Task]] = []
        if needs_order:
            tasks.append(
                (
                    "订单",
                    asyncio.create_task(
                        send_text_to_agent(
                            ORDER_AGENT_URL,
                            query,
                            caller_name="Triage Agent",
                            target_name="Order Agent",
                        )
                    ),
                )
            )
        if needs_logistics and not any(name == "物流" for name, _ in tasks):
            tasks.append(
                (
                    "物流",
                    asyncio.create_task(
                        send_text_to_agent(
                            LOGISTICS_AGENT_URL,
                            query,
                            caller_name="Triage Agent",
                            target_name="Logistics Agent",
                        )
                    ),
                )
            )
        if needs_policy and not any(name == "规则" for name, _ in tasks):
            tasks.append(
                (
                    "规则",
                    asyncio.create_task(
                        send_text_to_agent(
                            POLICY_AGENT_URL,
                            query,
                            caller_name="Triage Agent",
                            target_name="Policy Agent",
                        )
                    ),
                )
            )

        if not tasks:
            tasks.append(
                (
                    "规则",
                    asyncio.create_task(
                        send_text_to_agent(
                            POLICY_AGENT_URL,
                            query,
                            caller_name="Triage Agent",
                            target_name="Policy Agent",
                        )
                    ),
                )
            )

        results = await asyncio.gather(*(task for _, task in tasks))
        sections = [f"{name}Agent：{result}" for (name, _), result in zip(tasks, results)]
        draft = "我帮你联动客服系统看过了。\n" + "\n".join(sections)

        return polish_customer_reply(
            system_prompt=(
                "你是一名中文电商客服总协调。"
                "请把多个客服Agent的结果整合成一段自然、明确、可执行的回复。"
                "不要捏造事实，不要使用markdown。"
            ),
            user_prompt=f"用户问题：{query}\n候选结果：\n{draft}",
            fallback=draft,
        )

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")


def build_app():
    return build_a2a_app(build_agent_card(), TriageAgentExecutor())


if __name__ == "__main__":
    import uvicorn

    if is_debug_enabled():
        debug_log("Triage Agent", f"启动调试模式 | listen=http://localhost:{TRIAGE_AGENT_PORT}")
    uvicorn.run(build_app().build(), host="0.0.0.0", port=TRIAGE_AGENT_PORT)
