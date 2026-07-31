"""Standalone issue classification endpoint."""

from fastapi import APIRouter

from app.schemas.issue import IssueAnalysisRequest, IssueClassification
from app.services.issue_classifier import IssueClassifier

router = APIRouter(prefix="/issues", tags=["issues"])


@router.post("/analyze", response_model=IssueClassification)
async def analyze_issue(payload: IssueAnalysisRequest) -> IssueClassification:
    """Classify a single issue by title, body, and labels.

    This is a stateless rule-based classification. It does not require
    a repository to be synced first.
    """
    return IssueClassifier().classify(
        title=payload.title,
        body=payload.body,
        labels=payload.labels,
    )
