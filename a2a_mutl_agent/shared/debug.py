"""多智能体示例的调试输出辅助。"""

from __future__ import annotations

import os
import sys


def is_debug_enabled() -> bool:
    """是否开启调试模式。"""
    env_value = os.getenv("A2A_MUTL_AGENT_DEBUG", "").lower()
    return "--debug" in sys.argv or env_value in {"1", "true", "yes", "on"}


def preview_text(text: str, limit: int = 120) -> str:
    """压缩长文本，避免调试输出过长。"""
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "..."


def debug_log(owner: str, message: str) -> None:
    """按统一格式打印调试信息。"""
    if is_debug_enabled():
        print(f"[DEBUG][{owner}] {message}", flush=True)
