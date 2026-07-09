"""HTTP routes for the repository assistant."""

from fastapi import APIRouter, HTTPException

from app.assistant.harness import AgentHarness, AgentHarnessError
from app.schemas.assistant import AssistantChatRequest, AssistantChatResponse
from app.services.github_client import GitHubClientError

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
async def chat(payload: AssistantChatRequest) -> AssistantChatResponse:
    """Ask the repository assistant a question."""
    try:
        return await AgentHarness().answer(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except AgentHarnessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
