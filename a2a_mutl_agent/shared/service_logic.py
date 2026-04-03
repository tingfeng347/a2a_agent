"""客服场景的通用业务逻辑。"""

from __future__ import annotations

import re

from .mock_data import ORDERS, POLICY_TEXT, TRACKING_EVENTS


def extract_order_id(text: str) -> str:
    match = re.search(r"\bA\d{4}\b", text.upper())
    return match.group(0) if match else ""


def get_order(order_id: str) -> dict | None:
    return ORDERS.get(order_id.upper())


def get_tracking_events(order_id: str) -> list[str]:
    return TRACKING_EVENTS.get(order_id.upper(), [])


def contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def format_order_snapshot(order_id: str, order: dict) -> str:
    items = "、".join(order["items"])
    return (
        f"订单{order_id}，客户{order['customer']}，商品{items}，"
        f"当前状态{status_to_cn(order['status'])}，实付{order['paid_amount']}元，"
        f"退款状态：{order['refund_status']}。"
    )


def status_to_cn(status: str) -> str:
    mapping = {
        "processing": "待出库",
        "in_transit": "运输中",
        "delivered": "已签收",
        "delayed": "物流延迟",
    }
    return mapping.get(status, status)


def evaluate_return_eligibility(order: dict) -> str:
    if order["status"] == "processing":
        return "订单尚未发货，优先建议直接取消订单，无需走退货流程。"
    if order.get("activated"):
        return "该商品已激活，按当前规则不支持7天无理由退货。"
    if order.get("received") and order.get("opened"):
        return "商品已签收且已拆封，如不影响二次销售可申请售后审核。"
    if order.get("received"):
        return "订单已签收，若仍在7天内且商品完好，可申请7天无理由退货。"
    return "订单还在配送中，暂不支持直接退货，建议签收后或联系人工拦截。"


def refund_sla_text(order: dict) -> str:
    if "审核中" in order["refund_status"]:
        return "当前退款审核中，一般审核通过后1到3个工作日原路退回。"
    return POLICY_TEXT["refund"]


def logistics_summary(order_id: str, order: dict) -> str:
    events = get_tracking_events(order_id)
    last_event = events[-1] if events else "暂无物流轨迹"
    company = order["shipping_company"] or "暂未分配快递"
    tracking_no = order["tracking_no"] or "暂无单号"
    delay_text = f" 延迟原因：{order['delay_reason']}。" if order.get("delay_reason") else ""
    return (
        f"订单{order_id} 物流公司：{company}，运单号：{tracking_no}，"
        f"当前状态：{status_to_cn(order['status'])}，最新轨迹：{last_event}，"
        f"预计送达：{order['eta']}。{delay_text}"
    )


def policy_summary() -> str:
    return (
        f"退货规则：{POLICY_TEXT['return']} "
        f"退款时效：{POLICY_TEXT['refund']} "
        f"延迟补偿：{POLICY_TEXT['delay']}"
    )
