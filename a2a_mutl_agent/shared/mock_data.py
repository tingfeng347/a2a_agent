"""客服场景的示例订单、物流与售后规则数据。"""

from __future__ import annotations

ORDERS = {
    "A1001": {
        "customer": "张三",
        "items": ["降噪蓝牙耳机"],
        "status": "in_transit",
        "created_at": "2026-04-01 09:20",
        "paid_amount": 599,
        "shipping_company": "顺丰",
        "tracking_no": "SF10001",
        "eta": "2026-04-04 18:00前",
        "refund_status": "无退款申请",
        "received": False,
        "opened": False,
        "activated": False,
        "category": "数码配件",
    },
    "A1002": {
        "customer": "李四",
        "items": ["智能手表"],
        "status": "delivered",
        "created_at": "2026-03-28 14:10",
        "paid_amount": 1299,
        "shipping_company": "圆通",
        "tracking_no": "YT10002",
        "eta": "已于2026-03-30 16:20签收",
        "refund_status": "退款审核中，预计1-3个工作日原路退回",
        "received": True,
        "delivered_at": "2026-03-30 16:20",
        "opened": True,
        "activated": False,
        "category": "智能穿戴",
    },
    "A1003": {
        "customer": "王五",
        "items": ["游戏机械键盘"],
        "status": "processing",
        "created_at": "2026-04-03 08:30",
        "paid_amount": 399,
        "shipping_company": "",
        "tracking_no": "",
        "eta": "预计今日22:00前出库",
        "refund_status": "无退款申请",
        "received": False,
        "opened": False,
        "activated": False,
        "category": "电脑外设",
    },
    "A1004": {
        "customer": "赵六",
        "items": ["平板电脑"],
        "status": "delayed",
        "created_at": "2026-03-31 11:45",
        "paid_amount": 2599,
        "shipping_company": "京东物流",
        "tracking_no": "JD10004",
        "eta": "预计2026-04-05送达",
        "refund_status": "无退款申请",
        "received": False,
        "opened": True,
        "activated": True,
        "category": "数码整机",
        "delay_reason": "华东干线中转拥堵，包裹48小时未更新",
    },
}

TRACKING_EVENTS = {
    "A1001": [
        "04-01 11:20 商家已出库",
        "04-01 19:45 包裹已交给顺丰",
        "04-02 08:10 包裹已到达上海转运中心",
        "04-03 06:40 包裹运输中，预计今日晚些时候到达杭州",
    ],
    "A1002": [
        "03-28 18:20 商家已发货",
        "03-29 09:15 包裹到达广州分拨中心",
        "03-30 15:50 快件派送中",
        "03-30 16:20 已签收，签收人：本人",
    ],
    "A1003": [
        "04-03 08:30 订单已支付",
        "04-03 09:00 仓库正在拣货",
    ],
    "A1004": [
        "03-31 14:20 商家已出库",
        "04-01 10:10 包裹到达南京枢纽",
        "04-02 12:30 因干线拥堵暂缓转运",
        "04-03 12:30 包裹暂无新轨迹更新",
    ],
}

POLICY_TEXT = {
    "return": "支持7天无理由退货，但已激活的数码整机、定制商品、影响二次销售的商品不支持。",
    "refund": "退款审核通过后，通常1到3个工作日原路退回；银行卡到账可能再延后1到2天。",
    "delay": "物流48小时未更新可登记催件；若超承诺时效，可申请运费券或人工补偿。",
}
