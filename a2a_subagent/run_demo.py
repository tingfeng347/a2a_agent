"""一键启动子Agent演示。"""

from __future__ import annotations

import argparse
import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

AGENT_SPECS = [
    ("Weather Agent", "weather_agent.py", 10002),
    ("News Agent", "news_agent.py", 10003),
]


def is_port_open(port: int) -> bool:
    """检查本地端口是否已被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start_agents(debug: bool = False) -> list[subprocess.Popen]:
    """启动尚未运行的 agent 子进程。"""
    started: list[subprocess.Popen] = []

    for agent_name, script_name, port in AGENT_SPECS:
        if is_port_open(port):
            print(f"[launcher] 复用已运行的 {agent_name}，端口 {port}")
            continue

        command = [sys.executable, script_name]
        if debug:
            command.append("--debug")

        process = subprocess.Popen(command, cwd=ROOT_DIR)
        started.append(process)
        print(f"[launcher] 已启动 {agent_name}，端口 {port}")

    return started


def wait_for_agents(timeout_seconds: float = 10.0) -> None:
    """等待 agent 端口就绪。"""
    deadline = time.time() + timeout_seconds
    pending_ports = {port for _, _, port in AGENT_SPECS}

    while pending_ports and time.time() < deadline:
        pending_ports = {port for port in pending_ports if not is_port_open(port)}
        if pending_ports:
            time.sleep(0.2)

    if pending_ports:
        ports_text = ", ".join(str(port) for port in sorted(pending_ports))
        raise RuntimeError(f"这些端口上的 agent 没有在预期时间内启动成功：{ports_text}")


def stop_agents(processes: list[subprocess.Popen]) -> None:
    """关闭由当前脚本拉起的 agent 子进程。"""
    for process in processes:
        if process.poll() is None:
            process.terminate()

    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="MagicCode - A2A Agent 一键启动")
    parser.add_argument("--debug", action="store_true", help="启用debug模式")
    args = parser.parse_args()

    if args.debug:
        print("[DEBUG] Debug模式已启用")

    started_processes: list[subprocess.Popen] = []
    try:
        started_processes = start_agents(args.debug)
        wait_for_agents()
        print("[launcher] 子Agent已就绪，进入控制台。输入 exit 退出。")

        from agent_loop import MagicCode

        MagicCode(debug=args.debug).run()
    finally:
        stop_agents(started_processes)


if __name__ == "__main__":
    main()
