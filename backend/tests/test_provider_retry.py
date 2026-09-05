from unittest.mock import AsyncMock

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from app.openai_provider import ProviderConfigurationError, ProviderResponseError
from app.providers import (
    ProviderRetry,
    classify_provider_error,
    retry_external,
)


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.openai.com/v1/responses")


def _status_response(
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    return httpx2.Response(status_code, request=_request(), headers=headers)


@pytest.mark.parametrize(
    ("error", "retryable", "reason_code"),
    [
        (APITimeoutError(_request()), True, "timeout"),
        (APIConnectionError(request=_request()), True, "connection_error"),
        (
            APIStatusError(
                "private request-timeout detail",
                response=_status_response(408),
                body=None,
            ),
            True,
            "timeout",
        ),
        (
            RateLimitError(
                "private rate-limit detail",
                response=_status_response(429),
                body={"private": "provider output"},
            ),
            True,
            "rate_limited",
        ),
        (
            RateLimitError(
                "private quota detail",
                response=_status_response(429),
                body={"error": {"code": "insufficient_quota"}},
            ),
            False,
            "quota_exceeded",
        ),
        (
            InternalServerError(
                "private server detail",
                response=_status_response(500),
                body={"private": "provider output"},
            ),
            True,
            "server_error",
        ),
        (
            APIStatusError(
                "private conflict detail",
                response=_status_response(409),
                body=None,
            ),
            True,
            "conflict",
        ),
        (
            APIStatusError(
                "private no-retry detail",
                response=_status_response(
                    500,
                    headers={"x-should-retry": "false"},
                ),
                body=None,
            ),
            False,
            "server_error",
        ),
        (
            AuthenticationError(
                "private authentication detail",
                response=_status_response(
                    401,
                    headers={"x-should-retry": "true"},
                ),
                body=None,
            ),
            False,
            "client_error",
        ),
        (
            BadRequestError(
                "private request detail",
                response=_status_response(400),
                body=None,
            ),
            False,
            "client_error",
        ),
        (
            ProviderConfigurationError("private configuration detail"),
            False,
            "configuration_error",
        ),
        (
            ProviderResponseError("private response detail"),
            False,
            "invalid_response",
        ),
        (RuntimeError("private unknown detail"), False, "unknown_error"),
    ],
)
def test_classify_provider_error_uses_stable_sanitized_categories(
    error: Exception,
    retryable: bool,
    reason_code: str,
) -> None:
    classification = classify_provider_error(error)

    assert classification.retryable is retryable
    assert classification.reason_code == reason_code
    assert "private" not in repr(classification)


@pytest.mark.asyncio
async def test_retry_external_retries_two_transient_failures_then_succeeds() -> None:
    failures = [
        APIConnectionError(request=_request()),
        APITimeoutError(_request()),
    ]
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if failures:
            raise failures.pop(0)
        return "completed"

    sleep = AsyncMock()
    on_retry = AsyncMock()

    result = await retry_external(
        operation,
        max_attempts=3,
        initial_delay_seconds=0.25,
        sleep=sleep,
        on_retry=on_retry,
        jitter=lambda delay: delay,
    )

    assert result == "completed"
    assert calls == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.25, 0.5]
    assert [call.args[0] for call in on_retry.await_args_list] == [
        ProviderRetry(
            attempt=1,
            max_attempts=3,
            delay_seconds=0.25,
            reason_code="connection_error",
        ),
        ProviderRetry(
            attempt=2,
            max_attempts=3,
            delay_seconds=0.5,
            reason_code="timeout",
        ),
    ]


@pytest.mark.asyncio
async def test_retry_external_does_not_retry_permanent_failure() -> None:
    expected_error = ProviderResponseError("private invalid response")
    operation = AsyncMock(side_effect=expected_error)
    sleep = AsyncMock()
    on_retry = AsyncMock()

    with pytest.raises(ProviderResponseError) as error:
        await retry_external(
            operation,
            max_attempts=3,
            initial_delay_seconds=0.25,
            sleep=sleep,
            on_retry=on_retry,
            jitter=lambda delay: delay,
        )

    assert error.value is expected_error
    operation.assert_awaited_once()
    sleep.assert_not_awaited()
    on_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_external_stops_after_transient_attempt_budget() -> None:
    expected_error = APIConnectionError(request=_request())
    operation = AsyncMock(side_effect=expected_error)
    sleep = AsyncMock()
    on_retry = AsyncMock()

    with pytest.raises(APIConnectionError) as error:
        await retry_external(
            operation,
            max_attempts=3,
            initial_delay_seconds=0.25,
            sleep=sleep,
            on_retry=on_retry,
            jitter=lambda delay: delay,
        )

    assert error.value is expected_error
    assert operation.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.25, 0.5]
    assert on_retry.await_count == 2


@pytest.mark.asyncio
async def test_retry_external_respects_bounded_provider_retry_after() -> None:
    rate_limit_error = RateLimitError(
        "private rate-limit detail",
        response=_status_response(429, headers={"retry-after": "0.75"}),
        body=None,
    )
    operation = AsyncMock(side_effect=[rate_limit_error, "completed"])
    sleep = AsyncMock()
    on_retry = AsyncMock()

    result = await retry_external(
        operation,
        max_attempts=2,
        initial_delay_seconds=0.25,
        sleep=sleep,
        on_retry=on_retry,
    )

    assert result == "completed"
    sleep.assert_awaited_once_with(0.75)
    assert on_retry.await_args.args[0].delay_seconds == 0.75


@pytest.mark.parametrize(
    ("max_attempts", "initial_delay_seconds", "expected_message"),
    [
        (0, 0.25, "max_attempts must be between 1 and 5"),
        (6, 0.25, "max_attempts must be between 1 and 5"),
        (3, -0.1, "initial_delay_seconds must be between 0 and 60"),
        (3, 61.0, "initial_delay_seconds must be between 0 and 60"),
    ],
)
@pytest.mark.asyncio
async def test_retry_external_rejects_invalid_policy_before_operation(
    max_attempts: int,
    initial_delay_seconds: float,
    expected_message: str,
) -> None:
    operation = AsyncMock()

    with pytest.raises(ValueError, match=expected_message):
        await retry_external(
            operation,
            max_attempts=max_attempts,
            initial_delay_seconds=initial_delay_seconds,
        )

    operation.assert_not_awaited()
