# jyf负责部分计划

## 功能需求

Issue智能分析和监听功能

- 自动监听项目中新提交的Issue，并识别其类型，如使用问题、重复问题、信息不充分的问题、缺陷修复请求或功能改进请求等。
- 对于无需修改代码的问题，如重复Issue、使用咨询、信息不足等，系统能够自动生成回复内容并给出理由。


## 大体任务

1. 实现监听功能
    - 在第一部分的后端的完成基础上，可能需要增加webhook


2. 分析问题
    - 结合第二部分的ai功能，可能需要增加一些功能
    - 如果是无需修改代码的问题（不是bug），自动总结生成回复并给出理由
    - 如果是代码的bug
        - 够结合Issue描述、项目上下文和历史记录定位相关模块与文件
        - 生成修复方案并自动修改代码，完成后创建新的分支、提交修改并发起Pull Request

## 已完成部分（2026-07-06）

### Webhook 监听模块

新建独立模块 `backend/app/webhooks/`，与 `api/`、`services/` 同级。

**结构：**
```
backend/app/webhooks/
├── __init__.py      # 模块标记
├── router.py        # POST /api/webhooks/github 端点
└── handler.py       # 签名验证 + 事件分发 + Issue 分类处理
```

**功能：**
- 接收 GitHub Webhook 推送的 Issue 事件
- HMAC-SHA256 签名验证（`X-Hub-Signature-256`），未配置 secret 时自动跳过（开发模式）
- 按 `X-GitHub-Event` 分发事件，当前实现 `issues` 事件处理
- 仅处理 `action == "opened"` 的新建 Issue
- 调用已有的 `IssueClassifier` 规则分类器进行分类（BUG / FEATURE_REQUEST / QUESTION / DOCUMENTATION / DUPLICATE / INFO_NEEDED / INVALID / MAINTENANCE / UNKNOWN）
- 事件记录存入内存 `webhook_event_store`
- 如果仓库已通过手动同步存在，自动追加新 Issue 并重新计算分类统计

**配置项：**
- `GITHUB_WEBHOOK_SECRET` — 环境变量，用于签名验证

**使用方式：**
```bash
# 开发（不设 secret，跳过签名验证）
uv run uvicorn app.main:app --reload --port 8000

# 生产（设 secret，签名验证生效）
GITHUB_WEBHOOK_SECRET=your_secret uv run uvicorn app.main:app --port 8000
```

**后续需要对接 LLM 模块（等待另一位同学）：**
- `handle_issue_event` 函数中，规则分类后加 LLM 复核
- 非 BUG 类 Issue 自动生成回复草稿
- BUG 类 Issue 定位相关文件并生成修复方案

### 测试

新建 `backend/tests/test_webhooks/`，22 个测试全部通过：

| 文件 | 数量 | 内容 |
|---|---|---|
| `test_handler.py` | 14 个 | 签名验证、Issue 分类、事件分发、边缘情况 |
| `test_router.py` | 8 个 | HTTP 端点集成测试（无 secret / 有 secret） |

运行方式：`cd backend && uv run pytest`

### 修改的现有文件

| 文件 | 改动 |
|---|---|
| `backend/app/core/config.py` | 新增 `github_webhook_secret` 配置项 |
| `backend/app/main.py` | 注册 webhooks 路由 |
| `backend/.env.example` | 新增 `GITHUB_WEBHOOK_SECRET=` |
| `backend/pyproject.toml` | 新增 pytest 配置 + 开发依赖 |

## Vibe
