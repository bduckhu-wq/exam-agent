"""
Harness 层 - 异常处理与重试机制
"""
import asyncio
import functools
import time
from typing import Callable, Any, Optional
from .logger import get_logger


class AgentError(Exception):
    """Agent 基础异常"""
    pass


class LLMError(AgentError):
    """LLM 调用失败"""
    pass


class SkillNotFoundError(AgentError):
    """Skill 未找到"""
    pass


class NodeExecutionError(AgentError):
    """节点执行失败"""
    pass


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
    retry_on: tuple = (Exception,),
):
    """
    带指数退避的重试装饰器

    Args:
        max_attempts: 最大重试次数
        base_delay: 初始延迟（秒）
        max_delay: 最大延迟（秒）
        exponential_base: 指数基数
        retry_on: 需要重试的异常类型
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger = get_logger()
            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as e:
                    last_error = e
                    if attempt == max_attempts:
                        logger.logger.warning(
                            f"❌ {func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise

                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    logger.logger.warning(
                        f"⚠️  {func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)

            raise last_error

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as e:
                    last_error = e
                    if attempt == max_attempts:
                        raise

                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    time.sleep(delay)

            raise last_error

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def with_node_error_handling(node_name: str):
    """
    节点执行包装器：自动记录日志 + 降级处理

    用法：
        @with_node_error_handling("analyze")
        def analyze_node(state):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger = get_logger()
            request_id = kwargs.get("request_id", "unknown")

            logger.log_node_start(request_id, node_name)
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                logger.log_node_end(request_id, node_name, duration_ms, "ok")
                return result

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.log_node_end(request_id, node_name, duration_ms, f"error: {e}")

                # 降级处理：返回带错误信息的状态，不中断整个流程
                return {
                    "status": "error",
                    f"{node_name}_error": str(e),
                    "error_node": node_name,
                }

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger = get_logger()
            request_id = kwargs.get("request_id", "unknown")

            logger.log_node_start(request_id, node_name)
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                logger.log_node_end(request_id, node_name, duration_ms, "ok")
                return result

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.log_node_end(request_id, node_name, duration_ms, f"error: {e}")

                return {
                    "status": "error",
                    f"{node_name}_error": str(e),
                    "error_node": node_name,
                }

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class CircuitBreaker:
    """
    熔断器：防止 LLM 持续失败导致系统雪崩

    当错误率超过阈值时，暂时"熔断"（不再调用），等待恢复
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_attempts: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_attempts = half_open_attempts

        self.failures = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed | open | half_open

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()

        if self.failures >= self.failure_threshold:
            self.state = "open"

    def record_success(self):
        if self.state == "half_open":
            self.failures = 0
            self.state = "closed"

    def can_execute(self) -> bool:
        if self.state == "closed":
            return True

        if self.state == "open":
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = "half_open"
                return True
            return False

        # half_open: 允许少量尝试
        return True

    def get_state(self) -> dict:
        return {
            "state": self.state,
            "failures": self.failures,
            "last_failure": self.last_failure_time,
        }


# 全局熔断器
_llm_circuit_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    return _llm_circuit_breaker
