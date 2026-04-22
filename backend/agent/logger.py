"""
Harness 层 - Agent 执行日志
记录每个请求的完整链路：路由、节点执行、耗时、结果
"""
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Any
from functools import wraps
import asyncio


class AgentLogger:
    """
    轻量级 Agent 执行日志

    记录内容：
    - 请求 ID、session_id
    - 路由到的 Skill
    - 每个节点的执行：开始时间、结束时间、耗时
    - LLM 调用：token 消耗（如果有）
    - 最终结果或异常
    """

    def __init__(self, log_dir: str = "./logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("exam-agent")
        logger.setLevel(logging.INFO)

        # 文件 handler
        today = datetime.now().strftime("%Y%m%d")
        fh = logging.FileHandler(
            self.log_dir / f"agent_{today}.log",
            encoding="utf-8"
        )
        fh.setLevel(logging.INFO)

        # 控制台 handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        # 格式
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%H:%M:%S"
        )
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)

        logger.addHandler(fh)
        logger.addHandler(ch)

        return logger

    def log_request(
        self,
        request_id: str,
        session_id: str,
        user_input: str,
        skill: str,
    ):
        self.logger.info(
            f"[{request_id}] 📥 REQUEST | session={session_id} | skill={skill} | input={user_input[:50]}..."
        )

    def log_node_start(self, request_id: str, node: str):
        self.logger.info(f"[{request_id}] ▶️  NODE START | {node}")

    def log_node_end(
        self,
        request_id: str,
        node: str,
        duration_ms: float,
        status: str = "ok",
    ):
        emoji = "✅" if status == "ok" else "❌"
        self.logger.info(
            f"[{request_id}] {emoji} NODE END | {node} | {duration_ms:.0f}ms | status={status}"
        )

    def log_llm_call(
        self,
        request_id: str,
        model: str,
        prompt_tokens: int = None,
        completion_tokens: int = None,
        duration_ms: float = None,
        error: str = None,
    ):
        if error:
            self.logger.warning(
                f"[{request_id}] ⚠️  LLM ERROR | model={model} | error={error}"
            )
        else:
            tokens = ""
            if prompt_tokens or completion_tokens:
                tokens = f" | tokens={prompt_tokens or '?'}+{completion_tokens or '?'}"
            duration = f" | {duration_ms:.0f}ms" if duration_ms else ""
            self.logger.info(
                f"[{request_id}] 🤖 LLM CALL | model={model}{tokens}{duration}"
            )

    def log_result(
        self,
        request_id: str,
        status: str,
        questions_count: int = 0,
        duration_ms: float = 0,
        error: str = None,
    ):
        if error:
            self.logger.error(f"[{request_id}] ❌ RESULT | {error}")
        else:
            self.logger.info(
                f"[{request_id}] ✅ RESULT | questions={questions_count} | total={duration_ms:.0f}ms"
            )

    def log_session(self, session_id: str, action: str, detail: str = ""):
        self.logger.info(f"[SESSION] {action} | {session_id} | {detail}")


# 全局实例
_logger: Optional[AgentLogger] = None


def get_logger(log_dir: str = "./logs") -> AgentLogger:
    global _logger
    if _logger is None:
        _logger = AgentLogger(log_dir)
    return _logger
