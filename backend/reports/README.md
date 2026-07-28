# Issue 智能分类子系统单元测试

## 测试对象

- 被测代码：`app/services/issue_classifier.py`
- 测试代码：`tests/test_services/test_issue_classifier_unit.py`
- 测试框架：pytest
- Mock 工具：`unittest.mock.AsyncMock`

测试内容包括规则分类、空正文、未知类别、统计结果，以及 LLM 返回正常、返回异常和调用失败时的处理。

## 测试结果

- 单元测试：16 项通过
- 语句总数：79
- 未覆盖语句：2
- 语句覆盖率：97%
- 覆盖率要求：不低于 90%

## 报告文件

- `junit-issue-classifier.xml`：JUnit 测试报告
- `coverage-summary.txt`：覆盖率摘要
- `coverage.xml`：XML 格式覆盖率报告
- `coverage-html/index.html`：HTML 覆盖率报告首页

## 重新执行

在 `backend` 目录运行：

```bash
uv sync
uv run pytest tests/test_services/test_issue_classifier_unit.py -q \
  --junitxml=reports/junit-issue-classifier.xml \
  --cov=app.services.issue_classifier \
  --cov-report=term-missing \
  --cov-report=html:reports/coverage-html \
  --cov-report=xml:reports/coverage.xml \
  --cov-fail-under=90
```

当覆盖率低于 90% 或任意测试失败时，命令会返回失败。
