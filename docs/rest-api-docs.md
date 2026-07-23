# IssueScope API 接口文档

> 系统涉及的所有 API 端点：外部 GitHub REST API + 内部 IssueScope API。

---

## 第一部分：GitHub REST API（外部）

所有请求通过 `backend/app/services/github_client.py` 封装。

### 通用说明

- **Base URL**: `https://api.github.com`
- **认证**: `Authorization: Bearer <GITHUB_TOKEN>`
- **版本头**: `X-GitHub-Api-Version: 2022-11-28`
- **限速**: 有 token 5000 次/小时，无 token 60 次/小时

### 读取接口

| 方法 | 路径 | 说明 | 源码 |
|------|------|------|------|
| GET | `/repos/{owner}/{name}` | 仓库元数据 | `get_repository()` |
| GET | `/repos/{owner}/{name}/languages` | 语言分布 | `get_languages()` |
| GET | `/repos/{owner}/{name}/readme` | README（base64 解码） | `get_readme()` |
| GET | `/repos/{owner}/{name}/git/trees/{branch}?recursive=1` | 文件树 | `get_tree()` |
| GET | `/repos/{owner}/{name}/contents/{path}?ref={branch}` | 文件内容 | `get_file_content()` |
| GET | `/repos/{owner}/{name}/issues?state=all` | Issue 列表 | `get_issues()` |
| GET | `/repos/{owner}/{name}/pulls?state=all` | PR 列表 | `get_pull_requests()` |
| GET | `/repos/{owner}/{name}/commits` | Commit 列表 | `get_commits()` |

### 写入接口

| 方法 | 路径 | 说明 | 权限 | 源码 |
|------|------|------|------|------|
| POST | `/repos/{o}/{n}/issues/{num}/comments` | 评论 Issue | `issues:write` | `comment_on_issue()` |
| PATCH | `/repos/{o}/{n}/issues/{num}` | 更新 Issue（状态、标签） | `issues:write` | `update_issue()` |
| POST | `/repos/{o}/{n}/pulls` | 创建 PR | `pull_requests:write` | `create_pull_request()` |
| POST | `/repos/{o}/{n}/git/refs` | 创建分支 | `contents:write` | `create_branch()` |
| PUT | `/repos/{o}/{n}/contents/{path}` | 创建/修改文件 | `contents:write` | `create_or_update_file()` |

---

## 第二部分：IssueScope API（内部）

所有端点通过 FastAPI 提供，Base URL 由 `VITE_API_BASE_URL` 配置。

### 系统

#### `GET /api/health`

系统健康检查。

**响应**: `{"status": "ok"}`

---

### 仓库同步

#### `POST /api/repositories/sync`

同步 GitHub 仓库数据（拉取元数据、git clone、分类、构建知识图谱）。

**请求体**:

```json
{
  "url": "https://github.com/S1mpleWind/wgy666",
  "max_issues": 30,
  "max_pull_requests": 15,
  "max_commits": 12,
  "max_tree_items": 600
}
```

**响应**: `RepositorySnapshot`（含 identity、stats、files、issues、knowledge graph 等）

#### `GET /api/repositories`

列出已同步的仓库列表。

**响应**: `RepositoryListItem[]`

#### `GET /api/repositories/{owner}/{name}`

获取已同步仓库的快照（读缓存，不会重新拉取）。

**响应**: `RepositorySnapshot`

---

### Assistant / Agent

#### `POST /api/assistant/chat`

向仓库助手提问。

**请求体**:

```json
{
  "owner": "S1mpleWind",
  "name": "wgy666",
  "message": "这个项目的测试在哪？",
  "freshness": "cache_first",
  "history": []
}
```

**响应**:

```json
{
  "answer": "测试文件在 tests/ 目录下...",
  "repository": "S1mpleWind/wgy666",
  "used_cached_data": true,
  "tool_calls": [...],
  "citations": [...]
}
```

---

### Webhook

#### `POST /api/webhooks/github`

接收 GitHub Webhook 事件（需在 GitHub 仓库配置）。

**Headers**:
- `X-GitHub-Event`: 事件类型（`issues`、`pull_request` 等）
- `X-Hub-Signature-256`: HMAC-SHA256 签名
- `X-GitHub-Delivery`: 事件唯一 ID

**处理的事件**:

| 事件 | 动作 | 行为 |
|------|------|------|
| `issues` | `opened` | LLM 分类 + 通知 + 自动回复草稿 |
| `issues` | `reopened` | LLM 分类 + 通知（同 opened） |
| `issues` | `closed` | 更新快照 + 通知（前端自动刷新） |
| `issues` | `edited` / `labeled` | 忽略 |

**响应**: `{"status": "ok"}`

#### `GET /api/webhooks/events`

获取 Webhook 事件列表（前端通知轮询）。

**参数**: `limit=20`, `repository=owner/name`

#### `GET /api/webhooks/events/{event_id}`

获取单个事件详情（含 classification、auto_reply_draft）。

#### `PATCH /api/webhooks/events/{event_id}?action={read|delete}`

标记事件为已读或删除。

#### `POST /api/webhooks/events/{event_id}/reply`

确认回复——AgentHarness 生成回复并 post 到 GitHub。

**响应**:

```json
{
  "status": "ok",
  "reply_text": "回复内容...",
  "comment_url": "https://github.com/...",
  "source": "faq|llm"
}
```

#### `POST /api/webhooks/events/{event_id}/fix`

确认修复——AgentHarness 分析代码 → 建分支 → 改文件 → 提 PR。

**响应**:

```json
{
  "status": "ok",
  "pr_url": "https://github.com/.../pull/1",
  "branch_name": "auto-fix/issue-42"
}
```

#### `GET /api/webhooks/config`

获取 Webhook 配置（URL + 是否已配置 secret）。

---

### FAQ 知识库

#### `GET /api/faq`

列出所有 FAQ 条目。

**参数**: `?confirmed=true|false`

#### `POST /api/faq`

手动添加 FAQ。

**请求体**:

```json
{
  "question": "怎么部署后端",
  "answer": "执行 cd backend && uv run uvicorn..."
}
```

#### `PATCH /api/faq/{id}?action={confirm|unconfirm}`

确认/取消确认 FAQ 条目。

#### `PATCH /api/faq/{id}?action=edit`

编辑 FAQ 条目（可更新 question 和/或 answer）。

**请求体**（JSON，可选字段，传哪个更新哪个）:

```json
{
  "question": "新的问题",
  "answer": "新的回答"
}
```

更新 question 时会自动重新提取 keywords 和 embedding。

#### `DELETE /api/faq/{id}`

删除 FAQ 条目。

#### `POST /api/faq/generate?owner={owner}&name={name}`

自动生成 FAQ——分析已关闭 Issue 聚类 → LLM 总结 → 写入（待确认）。

**响应**:

```json
{
  "created": 0,
  "entries": [],
  "reason": "仓库暂无已关闭 Issue，无法自动生成 FAQ"
}
```

---

### 自动修复 PR 完整流程

```
POST /events/{id}/fix
  │
  ├─ AgentHarness.run() → LLM 调工具探索代码
  ├─ 解析 JSON → FixFileChange 列表
  ├─ create_branch()       POST /repos/{o}/{n}/git/refs
  ├─ create_or_update_file() PUT /repos/{o}/{n}/contents/{path}
  └─ create_pull_request()  POST /repos/{o}/{n}/pulls
```
