import re
from typing import override

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


def extract_location(query: str) -> str:
    cleaned = re.sub(
        r"(帮我|请|查一下|查下|查询|看看|看下|一下|今天|明天|后天|现在|当前|想知道|想看)",
        "",
        query,
    )
    patterns = [
        r"([A-Za-z\u4e00-\u9fa5]+?)(?:的)?(?:天气|气温|温度|下雨|降雨)",
        r"(?:去|到)([A-Za-z\u4e00-\u9fa5]+)(?:出差|旅游|玩|旅行)",
    ]
    for pattern in patterns:
        matched = re.search(pattern, cleaned)
        if matched:
            return matched.group(1).strip()
    stripped = re.sub(
        r"(天气|气温|温度|下雨|降雨|吗|怎么样)",
        "",
        cleaned,
    )
    stripped = re.sub(r"[？?。！，,\s]", "", stripped)
    return stripped[:20]


WEATHER_CODE_MAP = {
    0: "晴朗",
    1: "大体晴",
    2: "局部多云",
    3: "阴天",
    45: "有雾",
    48: "冻雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "浓毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    95: "雷暴",
}


def weather_code_to_text(code: int) -> str:
    return WEATHER_CODE_MAP.get(code, f"天气代码{code}")


async def query_weather(location: str) -> str:
    if not location:
        return "天气子Agent没有识别到城市，请在问题里明确城市名称。"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        geo_resp = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "zh", "format": "json"},
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()
        results = geo_data.get("results") or []
        if not results:
            return f"天气子Agent没有找到“{location}”对应的城市。"

        place = results[0]
        weather_resp = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "forecast_days": 1,
                "timezone": "auto",
            },
        )
        weather_resp.raise_for_status()
        data = weather_resp.json()

    current = data["current"]
    daily = data["daily"]
    desc = weather_code_to_text(int(current["weather_code"]))
    max_temp = daily["temperature_2m_max"][0]
    min_temp = daily["temperature_2m_min"][0]
    feels_like = current["apparent_temperature"]
    humidity = current["relative_humidity_2m"]
    wind = current["wind_speed_10m"]
    resolved_name = place["name"]

    return (
        f"天气子Agent结果：{resolved_name}当前{desc}，实时温度{current['temperature_2m']}摄氏度，"
        f"体感{feels_like}摄氏度，今天最高{max_temp}摄氏度，最低{min_temp}摄氏度，"
        f"湿度{humidity}%，风速{wind}公里每小时。"
    )


class WeatherAgentExecutor(AgentExecutor):
    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if not context.message:
            raise Exception("No message provided")

        query = context.get_user_input()
        location = extract_location(query)

        try:
            answer = await query_weather(location)
        except Exception as exc:
            answer = f"天气子Agent查询失败：{exc}"

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                context_id=context.context_id,  # type: ignore[arg-type]
                task_id=context.task_id,  # type: ignore[arg-type]
                artifact=new_text_artifact(name="weather_result", text=answer),
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
    skill = AgentSkill(
        id="weather_query",
        name="weather query agent",
        description="查询天气信息并返回简明结果",
        tags=["weather", "forecast"],
        examples=["帮我查一下上海今天的天气"],
    )
    agent_card = AgentCard(
        name="Weather Agent",
        description="A2A 天气子Agent",
        url="http://localhost:10002/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )
    handler = DefaultRequestHandler(
        agent_executor=WeatherAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )
    return A2AStarletteApplication(agent_card=agent_card, http_handler=handler)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_app().build(), host="0.0.0.0", port=10002)
