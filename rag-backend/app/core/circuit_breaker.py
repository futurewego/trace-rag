from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import pybreaker

from app.config import get_settings
from app.core.exceptions import CircuitOpenError

F = TypeVar("F", bound=Callable[..., Any])


def make_circuit_breaker(name: str) -> pybreaker.CircuitBreaker:
    """为指定服务创建熔断器实例"""
    settings = get_settings()
    return pybreaker.CircuitBreaker(
        fail_max=settings.circuit_breaker_fail_max,
        reset_timeout=settings.circuit_breaker_reset_timeout,
        name=name,
        listeners=[_LoggingListener(name)],
    )


class _LoggingListener(pybreaker.CircuitBreakerListener):
    def __init__(self, name: str) -> None:
        self.name = name

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: pybreaker.CircuitBreakerState,
        new_state: pybreaker.CircuitBreakerState,
    ) -> None:
        from app.observability.logger import get_logger

        logger = get_logger(__name__)
        logger.warning(
            "circuit_breaker_state_change",
            service=self.name,
            old_state=old_state.name,
            new_state=new_state.name,
        )

    def failure(self, cb: pybreaker.CircuitBreaker, exc: BaseException) -> None:
        from app.observability.logger import get_logger
        from app.observability.metrics import circuit_breaker_failures

        get_logger(__name__).warning(
            "circuit_breaker_failure",
            service=self.name,
            error=str(exc),
            fail_count=cb.fail_counter,
        )
        circuit_breaker_failures.labels(service=self.name).inc()


def with_circuit_breaker(cb: pybreaker.CircuitBreaker) -> Callable[[F], F]:
    """装饰器：用熔断器包裹异步函数，并将 CircuitBreakerError 转换为 CircuitOpenError"""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await cb.call_async(func, *args, **kwargs)
            except pybreaker.CircuitBreakerError as e:
                raise CircuitOpenError(cb.name) from e

        return wrapper  # type: ignore[return-value]

    return decorator


# ── 全局熔断器实例（延迟初始化）────────────────────────────────────────────────

_breakers: dict[str, pybreaker.CircuitBreaker] = {}


def get_breaker(service: str) -> pybreaker.CircuitBreaker:
    if service not in _breakers:
        _breakers[service] = make_circuit_breaker(service)
    return _breakers[service]
