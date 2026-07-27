"""Measure the cost of 1,000 rule-based issue classifications."""

import json
import time
from pathlib import Path

from app.services.issue_classifier import IssueClassifier


def main() -> None:
    classifier = IssueClassifier()
    iterations = 1_000
    started = time.perf_counter()
    for _ in range(iterations):
        classifier.classify(
            title="Bug: request fails after login",
            body="The API raises an exception and returns an error.",
            labels=["bug"],
        )
    elapsed_seconds = time.perf_counter() - started

    result = {
        "operation": "IssueClassifier.classify",
        "iterations": iterations,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "elapsed_milliseconds": round(elapsed_seconds * 1_000, 3),
        "average_microseconds": round(elapsed_seconds * 1_000_000 / iterations, 3),
    }
    report_path = Path(__file__).resolve().parents[1] / "reports" / "performance.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
