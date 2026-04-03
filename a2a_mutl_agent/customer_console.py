"""命令行体验入口：把用户问题发送给客服接待 Agent。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from config import TRIAGE_AGENT_URL
from shared.a2a_client import send_text_to_agent
from shared.debug import debug_log, is_debug_enabled, preview_text


async def main() -> None:
    print("客服多智能体演示已启动，请先分别运行 triage/order/policy/logistics 四个 agent。")
    print("示例：订单A1001到哪了；订单A1002退款什么时候到账；订单A1004延迟了可以补偿吗")

    if is_debug_enabled():
        debug_log("Customer Console", f"调试模式已开启 | cwd={Path.cwd()}")

    while True:
        user_input = input("customer> ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break
        debug_log("Customer Console", f"<= 用户输入 | query={preview_text(user_input)}")
        result = await send_text_to_agent(
            TRIAGE_AGENT_URL,
            user_input,
            caller_name="Customer Console",
            target_name="Triage Agent",
        )
        print(f"service> {result}\n")


if __name__ == "__main__":
    asyncio.run(main())
