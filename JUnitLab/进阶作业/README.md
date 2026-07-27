# 进阶工程：Mock 单元测试

本目录对应课程的 Mock 单元测试进阶要求，测试对象是本地项目后端的 `IssueClassifier` 服务。

## 内容

- `Mock代码/issue_classifier.py`：被测业务层
- `Mock代码/test_issue_classifier_unit.py`：使用 `AsyncMock` 模拟 OpenAI 异步客户端的单元测试
- `测试报告/junit-issue-classifier.xml`：JUnit XML 风格测试报告
- `覆盖率报告/coverage-summary.txt`：语句覆盖率摘要
- `覆盖率报告/app.services.issue_classifier.cover`：标准库 trace 生成的覆盖率明细

测试结果：16 个测试全部通过，目标模块语句覆盖率 99%。
