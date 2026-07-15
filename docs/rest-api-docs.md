# GitHub REST API 接口文档

> IssueScope 系统使用的 GitHub REST API 端点汇总。
> 所有请求均通过 `backend/app/services/github_client.py` 封装。

---

## 通用说明

- **Base URL**: `https://api.github.com`
- **认证**: `Authorization: Bearer <GITHUB_TOKEN>`
- **版本头**: `X-GitHub-Api-Version: 2022-11-28`
- **限速**: 有 token 5000 次/小时，无 token 60 次/小时

---

## 读取接口

### 获取仓库元数据

```
GET /repos/{owner}/{name}
```

**响应**: 仓库信息（owner、stats、topics 等）

**源码**: `GitHubClient.get_repository()`

---

### 获取仓库语言分布

```
GET /repos/{owner}/{name}/languages
```

**响应**: `{"Python": 5842000, "TypeScript": 892000, ...}`

**源码**: `GitHubClient.get_languages()`

---

### 获取 README

```
GET /repos/{owner}/{name}/readme
```

**响应**: 返回 JSON，其中 `content` 为 base64 编码的 README 文本

**处理**: `GitHubClient.get_readme()` 自动解码 base64，截断至 12KB

---

### 获取 Git Tree（文件树）

```
GET /repos/{owner}/{name}/git/trees/{branch}?recursive=1
```

**响应**: 仓库完整目录树（递归），含所有文件路径和类型

**源码**: `GitHubClient.get_tree()`

---

### 获取文件内容

```
GET /repos/{owner}/{name}/contents/{path}?ref={branch}
```

**响应**: 文件的 base64 编码内容

**处理**: `GitHubClient.get_file_content()` 自动解码，按 `rag_max_source_file_bytes` 截断

---

### 获取 Issues

```
GET /repos/{owner}/{name}/issues?state=all&sort=updated&direction=desc&per_page={limit}
```

**注意**: GitHub 的 `/issues` 端点同时返回 PR，需过滤 `pull_request` 字段

**源码**: `GitHubClient.get_issues()`

---

### 获取 Pull Requests

```
GET /repos/{owner}/{name}/pulls?state=all&sort=updated&direction=desc&per_page={limit}
```

**源码**: `GitHubClient.get_pull_requests()`

---

### 获取 Commits

```
GET /repos/{owner}/{name}/commits?per_page={limit}
```

**源码**: `GitHubClient.get_commits()`

---

## 写入接口

### 评论 Issue

```
POST /repos/{owner}/{name}/issues/{issue_number}/comments
```

**请求体**:

```json
{
  "body": "感谢反馈！这是一个 question 类型的问题..."
}
```

**权限**: `issues:write`

**源码**: `GitHubClient.comment_on_issue()`

---

### 更新 Issue

```
PATCH /repos/{owner}/{name}/issues/{issue_number}
```

**请求体**（可选字段，按需传入）:

```json
{
  "state": "closed",
  "labels": ["bug", "triaged"],
  "title": "新标题"
}
```

**权限**: `issues:write`

**源码**: `GitHubClient.update_issue()`

---

### 创建 Pull Request

```
POST /repos/{owner}/{name}/pulls
```

**请求体**:

```json
{
  "title": "修复 Issue #42：登录崩溃问题",
  "head": "fix-bug-login-crash",
  "base": "main",
  "body": "## 修复内容\n\n关闭 #42\n\n- 修复了空指针异常\n- 增加了空值检查"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `title` | 是 | PR 标题 |
| `head` | 是 | 修复分支名 |
| `base` | 是 | 目标分支（通常是 main） |
| `body` | 否 | PR 描述，支持 Markdown |

**权限**: `pull_requests:write`

**源码**: `GitHubClient.create_pull_request()`

**测试验证**:

```
替换 _post 为 fake 函数，验证:
  路径 → /repos/owner/repo/pulls
  body → { title, head, base, body }
```

---

### 创建分支

```
POST /repos/{owner}/{name}/git/refs
```

**请求体**:

```json
{
  "ref": "refs/heads/fix-bug-login-crash",
  "sha": "abc123def456..."
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `ref` | 是 | 完整引用路径 `refs/heads/{branch_name}` |
| `sha` | 是 | 基于哪个 commit 创建分支 |

**权限**: `contents:write`

**源码**: `GitHubClient.create_branch()`

---

### 创建/更新文件

```
PUT /repos/{owner}/{name}/contents/{path}
```

**请求体**:

```json
{
  "message": "修复 Issue #42：添加空值检查",
  "content": "aW1wb3J0IG9zCgpkZWYgcmVhZF9jb25maWcoKToKICAgIA==",
  "branch": "fix-bug-login-crash",
  "sha": "abc123def456..."
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `message` | 是 | commit 信息 |
| `content` | 是 | 文件内容，**base64 编码** |
| `branch` | 是 | 目标分支 |
| `sha` | 更新时必填 | 文件当前 SHA（新建文件时省略） |

**获取已有文件的 SHA**: 先调 `GET /repos/{owner}/{name}/contents/{path}`，响应中的 `sha` 字段

**权限**: `contents:write`

**源码**: `GitHubClient.create_or_update_file()`

**测试验证**（mock `_put`）:

```python
async def fake_put(path, json_data=None):
    assert "owner/repo/contents/src/main.py" in path
    assert json_data["message"] == "Add main.py"
    assert base64.b64decode(json_data["content"]).decode() == "print('hello')"
    assert json_data["branch"] == "fix-bug"
    # 新建文件时不传 sha
    assert "sha" not in json_data
```

---

## 自动修复 PR 完整流程

以下按顺序调用可完成"收到 bug Issue → 自动修复 → 提 PR"：

```
1. KnowledgeGraphService.search()        # RAG 搜索定位相关源码
2. LLM: 分析 bug + 生成修复后的代码
3. create_branch(ref, "fix-issue-42", sha)  # 从 main 创建修复分支
4. create_or_update_file(ref, path, ...)    # 提交修改的文件（每个文件一次）
5. create_pull_request(ref, title, ...)     # 开 PR
```

各步骤对应 GitHub API：

| 步骤 | 方法 | API |
|------|------|-----|
| 建分支 | `create_branch()` | `POST /repos/{o}/{n}/git/refs` |
| 改文件 | `create_or_update_file()` | `PUT /repos/{o}/{n}/contents/{path}` |
| 开 PR | `create_pull_request()` | `POST /repos/{o}/{n}/pulls` |
