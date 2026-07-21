# IssueScope 功能管线文档

> 描述系统当前已实现的所有核心流程，从事件触发到最终输出的完整链路。

---

## 一、仓库同步管线

```
用户在前端输入仓库 URL → 点击「同步仓库」
  │ POST /api/repositories/sync
  ▼
① 解析 GitHub URL（owner/name）
  ▼
② GitHub REST API 拉取元数据
  ├─ 仓库信息（owner、stats、topics）
  ├─ 语言分布（Python: 5842000, TypeScript: ...）
  ├─ README 内容
  ├─ Issues 列表（含状态、标签、分类）
  ├─ Pull Requests 列表
  └─ Commits 列表
  ▼
③ git clone 仓库（深度 1，使用 GITHUB_TOKEN 认证，避免限速）
  ├─ 失败时自动重试 3 次（清理残留目录、指数退避）
  └─ 失败原因：网络问题 → 前端显示中文提示
  ▼
④ 文件分类（规则匹配文件名/路径）
  ├─ SOURCE / TEST / DOCS / CONFIG / CI_CD / DEPENDENCY / ...
  └─ 按优先级排序（小文件优先保留）
  ▼
⑤ Issue 分类（LLM 优先，规则兜底）
  ├─ async_classify() → LLM 始终运行（配置了 LLM_API_KEY 时）
  │   ├─ 无 key → 纯规则关键词匹配
  │   └─ 有 key → LLM 分类 + 生成 auto_reply_draft
  └─ IssueCategory: bug / feature_request / question / documentation
     duplicate / info_needed / invalid / maintenance / unknown
  ▼
⑥ 构建知识图谱
  ├─ Nodes: repo / directory / module / test / dependency / README
  ├─ Edges: contains / defines_module / tests_with / documents
  └─ Chunks: 概览 / 目录结构 / 模块 / 依赖 / 测试 / 源码分块
  ▼
⑦ 向量化（三级降级）
  ├─ ① 远程 Embedding API（EMBEDDING_API_KEY）
  ├─ ② 本地 sentence-transformers（LOCAL_EMBEDDING_ENABLED）
  └─ ③ 哈希回退（无语义，仅 token 级匹配）
  ▼
⑧ 持久化到数据库
  ├─ repositories 表
  ├─ repository_files 表
  ├─ repository_file_contents 表（源码）
  ├─ issues 表（含分类结果）
  ├─ pull_requests / commits 表
  ├─ knowledge_nodes / edges / chunks 表（含 pgvector embedding）
  └─ sync_runs 表（同步记录）
```

---

## 二、Webhook 事件管线

```
GitHub 推送事件 → POST /api/webhooks/github
  │ 验证 HMAC-SHA256 签名
  ▼
① dispatch_event()
  ├─ issues → handle_issue_event()
  └─ 其他事件类型 → 静默忽略
  ▼
② handle_issue_event()
  ├─ 只处理 action == "opened"
  │   edited / closed / reopened → 忽略
  ├─ 提取 title / body / labels / number / state / author
  ├─ async_classify(title, body, labels)
  │   ├─ LLM 可用 → 始终调 LLM（含 auto_reply_draft）
  │   └─ LLM 不可用或失败 → 规则降级
  └─ 存储 WebhookEventRecord
      ├─ 内存 webhook_event_store（快速访问）
      └─ PostgreSQL webhook_events 表（持久化）
  ▼
③ 前端轮询 GET /api/webhooks/events?limit=20
  ├─ 侧边栏「通知」按钮显示红点
  └─ 点开通知列表 → 每条显示分类标签 + 时间 + 理由
  ▼
④ 点开通知 → GET /events/{id} → IssueDetailModal
  ├─ Issue 元信息（编号、状态、作者、标签）
  ├─ 🤖 LLM 分类结果
  │   ├─ 分类标签（bug / question / ...）
  │   ├─ 置信度进度条
  │   ├─ 分析理由
  │   └─ 识别信号
  ├─ 🤖 自动回复草稿（如有）
  └─ 操作按钮（按分类显示不同操作）
```

---

## 三、自动回复管线（非 bug 类型）

```
前提: 收到 question / info_needed / documentation / feature_request 类型 Issue
  │
  ▼
前端 IssueDetailModal 显示「🤖 自动回复草稿」
  │
  ▼
用户点击「确认回复」
  │ POST /api/webhooks/events/{id}/reply
  ▼
① AgentHarness 加载仓库快照
  ▼
② 构建自定义 prompt（issue 标题 + body + labels）
  ▼
③ AgentHarness.run() 工具循环
  ├─ LLM 自主选择工具（search_files / readme_lookup / knowledge_graph_search）
  ├─ 探索代码库后生成回复
  └─ 返回回复文本
  ▼
④ GitHubClient.comment_on_issue() → post 到 GitHub
  ▼
前端显示「回复已发布 → 查看评论」
```

---

## 四、自动修复管线（bug 类型）

```
前提: 收到 bug 类型 Issue
  │
  ▼
前端 IssueDetailModal 显示「🔧 自动修复」
  │
  ▼
用户点击「确认修复并提 PR」
  │ POST /api/webhooks/events/{id}/fix
  ▼
① AutoFixService.fix_issue()
  ▼
② AgentHarness 加载仓库快照
  ▼
③ 构建 fix prompt（bug 描述 + 代码库上下文）
  ▼
④ AgentHarness.run() 工具循环
  ├─ LLM 自主调 tool 探索代码
  │   search_files → 搜索文件
  │   knowledge_graph_search → 理解结构
  │   readme_lookup → 检查文档
  ├─ 生成修复方案
  └─ 输出 JSON（文件路径 + 内容 + commit message）
  ▼
⑤ 解析 JSON → FixFileChange 列表
  ├─ 获取已有文件的 SHA（GitHub Contents API）
  └─ 组织 FixProposal
  ▼
⑥ GitHubClient.create_branch()
  ├─ 分支名: auto-fix/issue-{number}
  └─ 从 default_branch HEAD 创建
  ▼
⑦ GitHubClient.create_or_update_file()
  ├─ 每个修改的文件独立 commit
  └─ base64 编码文件内容 → PUT Contents API
  ▼
⑧ GitHubClient.create_pull_request()
  ├─ head: auto-fix/issue-{number}
  ├─ base: main
  └─ body: Closes #{number}
  ▼
前端显示「PR 已创建 → 查看 PR」
```

---

## 五、FAQ 知识库管线

```
收到 Issue → 回复前
  │
  ├─ ① faq_match(title + body)
  │     ├─ PG 模式 → embed query → cosine 距离 > 0.8 → 命中
  │     └─ 关键词降级 → 与 FAQ keywords 重叠 ≥ 2 → 命中
  │
  ├─ 命中 → 直接返回 FAQ.answer
  │     回复末尾标注: "此回复来自 FAQ 知识库（匹配度 XX%）"
  │     不调 LLM，秒回，免费
  │
  └─ 未命中 → 走 LLM Agent 生成回复
        回复末尾标注: "此回复来自 LLM Agent"
```

### FAQ 管理

| 端点 | 说明 |
|------|------|
| `GET /api/faq` | 列表（支持 ?confirmed=true/false） |
| `POST /api/faq` | 手动添加 |
| `PATCH /api/faq/{id}?action=confirm` | 确认/取消确认 |
| `DELETE /api/faq/{id}` | 删除 |
| `POST /api/faq/generate` | 自动生成——分析相似 Issue → LLM 总结 → 写入（待确认） |

### FAQ 数据流

```
自动生成:
  issues 表 → 按 category + 关键词聚类
    → 每组 ≥ 2 条 → LLM 总结 question + answer
    → 写入 faq_entries（is_confirmed=false）
  → 人工确认后生效

手动添加:
  前端页面 → POST /api/faq
    → 写入 faq_entries（is_confirmed=true）
    → 立即生效
```

---

## 六、长期记忆管线

```
自动修复成功 → fix_webhook_event()
  │
  ▼
log_fix_memory(issue_title, category, files_changed, fix_summary)
  │
  ▼
INSERT INTO fix_memory_logs
  ├─ issue_keywords: ["crash", "null", "login"]
  ├─ pattern_type: "null_check"（自动推断）
  └─ fix_summary: "Added null check before function call"

下次修复时（待接入）:
  get_similar_fixes(query_kws) → top-3 历史记录
    → 注入 AgentHarness prompt 作为参考
```

---

## 七、Agent 问答管线

```
用户在前端聊天面板输入问题
  │ POST /api/assistant/chat
  ▼
① AgentHarness.answer()
  ├─ 加载仓库快照（缓存策略: cache_first / refresh_if_stale / force_refresh）
  ├─ 构建 system prompt（含仓库名、数据新鲜度）
  └─ 追加历史消息（最近 6 轮）
  ▼
② AgentHarness.run() 工具循环（最多 3 轮）
  ├─ 第 1 轮
  │   LLM 判断是否需要调工具
  │   ├─ 不需要 → 直接回答 ✅
  │   └─ 需要 → 调工具 → 结果回灌 → 第 2 轮
  │
  ├─ 第 2 轮
  │   LLM 看工具结果 → 继续调工具或回答
  │
  └─ 第 3 轮（最大轮数）
      LLM 必须给出最终回答
  ▼
③ 返回 AssistantChatResponse
  ├─ answer: 最终回答（Markdown 渲染）
  ├─ tool_calls: 调用过的工具列表
  ├─ citations: 引用来源
  └─ used_cached_data: 是否使用了缓存
```

### 8.1 可用工具列表

| 工具名 | 作用 | 数据来源 |
|--------|------|---------|
| `repo_overview` | 仓库元数据（星标、语言、文件数） | repositories 表 |
| `project_structure` | 项目结构分析（目录、入口文件、技术栈） | 规则分析 |
| `search_files` | 按路径或分类搜索文件 | repository_files 表 |
| `list_issues` | 按分类或状态列出 Issue | issues 表 |
| `readme_lookup` | 查 README（支持关键词） | repository_file_contents 表 |
| `knowledge_graph_search` | 图结构 RAG 检索（源码 chunk） | knowledge_chunks 表 |
| `recent_activity` | 最近的 commit 和 PR | commits / pull_requests 表 |

---

## 九、各管线依赖关系

```
                    ┌──────────────────┐
                    │  GitHub REST API  │
                    └────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              │              │               │
              ▼              ▼               ▼
      ┌──────────┐  ┌────────────┐  ┌──────────────┐
      │ 同步管线  │  │ Webhook管线 │  │ Agent 管线    │
      │ sync     │  │ webhook    │  │ chat         │
      └────┬─────┘  └─────┬──────┘  └──────┬───────┘
           │              │                │
           ▼              ▼                ▼
      ┌─────────────────────────────────────────┐
      │           PostgreSQL 数据库              │
      │  repositories / issues / files / chunks │
      └─────────────────────────────────────────┘
           │              │
           ▼              ▼
      ┌──────────┐  ┌──────────┐
      │ 自动回复  │  │ 自动修复 │
      │ Service  │  │ Service  │
      └────┬─────┘  └────┬─────┘
           │              │
           ▼              ▼
      ┌──────────────────────────┐
      │    GitHub Write API      │
      │ comment / branch / file  │
      │ / PR                     │
      └──────────────────────────┘
```

---

## 十、存储布局

```
PostgreSQL (11 表 + pgvector)
├── repositories                  仓库基本信息
├── repository_snapshots          完整快照 JSON
├── repository_files              文件列表 + 分类
├── repository_file_contents      源码内容
├── issues                        Issue + 分类结果
├── pull_requests                 PR 列表
├── commits                       Commit 列表
├── sync_runs                     同步记录
├── knowledge_nodes               图节点
├── knowledge_edges               图边
├── knowledge_chunks              文本块 + vector embedding
└── webhook_events                Webhook 事件记录

内存
├── webhook_event_store           最新事件（WebhookEventRecord 字典）
└── InMemoryRepositoryStore       未配 DB 时的回退存储
```
