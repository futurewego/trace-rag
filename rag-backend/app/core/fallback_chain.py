from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.core.exceptions import CircuitOpenError, FallbackExhaustedError
from app.observability.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class FallbackResult:
    value: Any
    provider: str
    fallback_triggered: bool = False
    fallback_reason: str | None = None
    attempts: list[str] = field(default_factory=list)


class FallbackChain:
    """
    有序降级链：依次尝试 providers，第一个成功的返回结果。
    记录每次 fallback 的原因，供 retrieval_log 使用。
    """

    def __init__(self, providers: list[tuple[str, Callable[..., Any]]]) -> None:
        """
        providers: [(name, async_callable), ...]
        按顺序尝试，第一个成功的返回。
        """
        if not providers:
            raise ValueError("FallbackChain requires at least one provider")
        self._providers = providers

    async def run(self, *args: Any, **kwargs: Any) -> FallbackResult:
        """依次调用 providers，返回第一个成功的结果"""
        last_error: Exception | None = None
        attempts: list[str] = []

        for i, (name, func) in enumerate(self._providers):
            try:
                result = await func(*args, **kwargs)
                fallback_triggered = i > 0
                reason = f"Primary failed, used {name}" if fallback_triggered else None

                if fallback_triggered:
                    logger.warning(
                        "fallback_chain_activated",
                        active_provider=name,
                        failed_providers=attempts,
                        reason=str(last_error),
                    )

                return FallbackResult(
                    value=result,
                    provider=name,
                    fallback_triggered=fallback_triggered,
                    fallback_reason=reason,
                    attempts=attempts + [name],
                )
            except (CircuitOpenError, Exception) as e:
                logger.warning(
                    "fallback_chain_provider_failed",
                    provider=name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                attempts.append(name)
                last_error = e
                continue

        raise FallbackExhaustedError(
            f"All providers failed: {', '.join(attempts)}. Last error: {last_error}"
        )

    async def run_stream(
        self, *args: Any, **kwargs: Any
    ) -> AsyncGenerator[Any, None]:
        """
        降级链的流式版本：依次尝试 providers，返回第一个成功的 AsyncGenerator。
        注意：只有在获取到第一个 token 之前才能触发 fallback。
        """
        last_error: Exception | None = None

        for i, (name, func) in enumerate(self._providers):
            try:
                gen = func(*args, **kwargs)
                # 先取第一个元素验证流是否可用
                first_item = None
                async for item in gen:
                    first_item = item
                    break

                if first_item is not None:
                    if i > 0:
                        logger.warning(
                            "fallback_chain_stream_activated",
                            active_provider=name,
                        )
                    yield first_item
                    async for item in gen:
                        yield item
                    return

            except (CircuitOpenError, Exception) as e:
                logger.warning(
                    "fallback_chain_stream_provider_failed",
                    provider=name,
                    error=str(e),
                )
                last_error = e
                continue

        raise FallbackExhaustedError(
            f"All streaming providers failed. Last error: {last_error}"
        )
