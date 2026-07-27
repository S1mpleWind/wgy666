# Unit Test Submission Reports

## Test target

The local project uses Python/FastAPI, so the equivalent of the requested
`BankAccountTest.java` is
`backend/tests/test_services/test_issue_classifier_unit.py`.
The target is the project's `IssueClassifier` service.

## Mock test

`_classifier_with_mock_client()` replaces the asynchronous OpenAI client with
`AsyncMock`. The tests verify a valid response, empty/invalid JSON, an invalid
category, and an exception without making a network request.

## Results

- Focused unit and Mock tests: 16 passed.
- Target statement coverage: 99% for `app/services/issue_classifier.py`.
- Performance test: 1,000 `IssueClassifier.classify` calls took 7.669 ms;
  average 7.669 microseconds per call. See `performance.json`.
- JUnit XML report: `junit-issue-classifier.xml`.
- Statement coverage report: `coverage/app.services.issue_classifier.cover`.

The full existing suite was also run: 154 passed, 5 skipped, and 8 existing
tests failed. Those failures are outside this submission; the focused tests
remain green.

## Reproduction

```bash
cd backend
PYTHONPATH=. .venv/bin/pytest tests/test_services/test_issue_classifier_unit.py -q
PYTHONPATH=. .venv/bin/python scripts/test_issue_classifier_performance.py
PYTHONPATH=. .venv/bin/python -m trace --count --missing --summary \
  --coverdir=reports/coverage --module pytest \
  tests/test_services/test_issue_classifier_unit.py -q
```
