"""可选的大模型润色辅助。"""

from __future__ import annotations

import os

import dotenv
from openai import OpenAI

dotenv.load_dotenv()

_MODEL = os.getenv("OPENAI_MODEL")
_BASE_URL = os.getenv("OPENAI_BASE_URL")
_API_KEY = os.getenv("OPENAI_API_KEY")
_CLIENT = OpenAI(base_url=_BASE_URL, api_key=_API_KEY) if (_MODEL and _BASE_URL and _API_KEY) else None


def polish_customer_reply(system_prompt: str, user_prompt: str, fallback: str) -> str:
    """使用大模型润色客服回复；若不可用则回退到原始文本。"""
    if _CLIENT is None or not _MODEL:
        return fallback

    try:
        response = _CLIENT.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            extra_body={"enable_thinking": False},
        )
        content = response.choices[0].message.content
        return content.strip() if content else fallback
    except Exception:
        return fallback
