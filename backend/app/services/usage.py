"""Per-user accounting helpers for external integration requests."""

from typing import Any
from uuid import UUID

from app.core.effective_config import get_effective_config


def record_integration_request(
    service: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    """Record usage when the current request belongs to an authenticated user."""
    user_id = get_effective_config().user_id
    if not user_id:
        return
    try:
        from app.storage.users import get_user_store

        get_user_store().record_usage(
            UUID(user_id),
            service,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    except Exception:
        return


async def tracked_chat_completion(client: Any, **kwargs: Any) -> Any:
    """Call an OpenAI-compatible chat completion and account for its usage."""
    try:
        completion = await client.chat.completions.create(**kwargs)
    except Exception:
        record_integration_request("llm")
        raise

    usage = getattr(completion, "usage", None)
    record_integration_request(
        "llm",
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )
    return completion
