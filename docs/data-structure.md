# IssueScope 数据结构文档

> 系统涉及的所有数据模型、数据库表结构、前后端接口类型及数据流。

---

## 一、核心枚举

### FileCategory — 文件分类

| 枚举值 | 含义 | 典型文件 |
|--------|------|---------|
| `source_code` | 源代码 | `.py`, `.js`, `.ts`, `.java`, `.go`, `.rs` |
| `tests` | 测试文件 | `test_*.py`, `*.spec.ts` |
| `documentation` | 文档 | `.md`, `.rst`, `.txt` |
| `configuration` | 配置 | `.json`, `.yaml`, `.toml`, `.cfg` |
| `ci_cd` | CI/CD | `.github/`, `Dockerfile`, `.gitlab-ci.yml` |
| `dependency` | 依赖清单 | `requirements.txt`, `package.json`, `go.mod` |
| `build` | 构建 | `Makefile`, `CMakeLists.txt`, `pyproject.toml` |
| `assets` | 静态资源 | `.png`, `.jpg`, `.svg`, `.css` |
| `data` | 数据文件 | `.csv`, `.jsonl`, `.sql` |
| `other` | 其他 | — |

**源码位置**: `backend/app/schemas/repository.py` — `class FileCategory(StrEnum)`

---

### IssueCategory — Issue 分类

| 枚举值 | 含义 | 典型关键词 |
|--------|------|-----------|
| `bug` | 缺陷 | bug, crash, error, exception, traceback, 报错, 崩溃 |
| `feature_request` | 功能请求 | feature, enhancement, proposal, 功能, 建议 |
| `question` | 使用咨询 | question, how to, help, usage, 怎么, 如何 |
| `documentation` | 文档问题 | doc, docs, documentation, readme, 文档 |
| `duplicate` | 重复 Issue | duplicate, same as, 重复 |
| `info_needed` | 信息不足 | reproduce, missing, more info, 复现, 信息不足 |
| `invalid` | 无效 Issue | invalid, wontfix, 无效 |
| `maintenance` | 维护事项 | refactor, cleanup, chore, deps, 维护 |
| `unknown` | 未分类 | — |

**源码位置**: `backend/app/schemas/issue.py` — `class IssueCategory(StrEnum)`

---

## 二、后端 Pydantic 模型

### 2.1 同步请求/响应

```
SyncRepositoryRequest            ← 用户发起同步
├── url: str                     GitHub 仓库 URL
├── max_issues: int = 30         Issue 同步上限
├── max_pull_requests: int = 20  PR 同步上限
├── max_commits: int = 20        Commit 同步上限
└── max_tree_items: int = 500    文件树采样上限

RepositorySnapshot               ← 同步返回
├── identity: RepositoryIdentity 仓库标识
│   ├── owner: str
│   ├── name: str
│   ├── full_name: str
│   ├── html_url: HttpUrl
│   └── default_branch: str
├── description: str | null
├── stats: RepositoryStats
│   ├── stars / forks / watchers: int
│   ├── open_issues: int
│   ├── size_kb: int
│   ├── primary_language: str | null
│   └── languages: dict[str, int]
├── topics: list[str]
├── readme: str | null
├── files: list[ClassifiedFile]
│   ├── path: str
│   ├── category: FileCategory
│   └── size: int | null
├── source_contents: list[RepositoryFileContent]     ← 源码（用于 RAG）
│   ├── path / category / content / size
│   └── truncated: bool
├── file_categories: list[CategorySummary]
├── issues: list[GitHubIssue]
├── issue_categories: list[CategorySummary]
├── pull_requests: list[PullRequestSummary]
├── recent_commits: list[CommitSummary]
└── synced_at: datetime
```

### 2.2 Issue 分类模型

```
IssueClassification              ← 分类结果
├── category: IssueCategory      分类标签
├── confidence: float            置信度 [0, 1]
├── reason: str                  分析理由
├── suggested_action: str        建议操作
├── signals: list[str]           识别信号（如 "bug:crash", "question:how to"）
└── auto_reply_draft: str | null LLM 生成的回复草稿

GitHubIssue                      ← 同步/Webhook 中的 Issue
├── number: int                  编号
├── title: str                   标题
├── state: str                   open / closed
├── html_url: HttpUrl            GitHub 链接
├── author: str | null           作者
├── labels: list[str]            标签
├── comments: int                评论数
├── created_at / updated_at: datetime | null
└── classification: IssueClassification
```

### 2.3 Agent / Chat 模型

```
AssistantChatRequest             ← 用户提问
├── owner: str                   仓库 owner
├── name: str                    仓库名
├── message: str                 问题内容
├── freshness: FreshnessMode     缓存策略
│   ├── cache_first              缓存优先
│   ├── refresh_if_stale         过期刷新（10 分钟 TTL）
│   └── force_refresh            强制刷新
└── history: list[ChatMessage]   对话历史

AssistantChatResponse            ← Agent 回答
├── answer: str                  最终回答（Markdown）
├── repository: str              仓库 full_name
├── used_cached_data: bool       是否使用缓存
├── tool_calls: list[AssistantToolCall]
│   ├── name: str                工具名
│   ├── args: dict               参数
│   └── summary: str             执行摘要
└── citations: list[AssistantCitation]
    ├── type: str                类型（file / issue / readme）
    ├── label: str               标签
    ├── url: HttpUrl | null      GitHub 链接
    └── path: str | null         文件路径
```

### 2.4 知识图谱模型

```
KnowledgeNode                    ← 图节点
├── key: str                     唯一键（如 "repo", "dir:src", "module:app"）
├── type: str                    类型（repository / directory / module / ...）
├── name: str                    显示名称
├── path: str | null             文件路径
├── summary: str                 摘要
└── metadata: dict               附加元数据

KnowledgeEdge                    ← 图边
├── source: str                  源节点 key
├── target: str                  目标节点 key
└── relation: str                关系（contains / defines_module / tests_with）

KnowledgeChunk                   ← 文本块（含向量）
├── key: str                     唯一键
├── title: str                   块标题
├── content: str                 文本内容
├── source_type: str             来源类型（source_code / test / doc / ...）
├── source_path: str | null      文件路径
├── node_keys: list[str]         关联节点
├── metadata: dict               元数据
└── embedding: list[float] | null 向量（1536 维，仅 PostgreSQL 模式）
```

### 2.5 Webhook 事件模型

```
WebhookEventRecord               ← 内存 / 数据库事件记录
├── event_id: str                GitHub 的 delivery ID
├── event_type: str              事件类型（"issues"）
├── action: str                  动作（"opened"）
├── repository: str              owner/name
├── issue_number: int
├── issue_title: str
├── issue_state: str             open / closed
├── issue_labels: list[str]
├── issue_author: str | null
├── classification: IssueClassification | null
├── received_at: datetime
└── raw_payload: dict            原始 GitHub payload
```

---

## 三、数据库表结构

### 3.1 repositories — 仓库元数据

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| owner | VARCHAR(255) | 仓库所有者 |
| name | VARCHAR(255) | 仓库名 |
| full_name | VARCHAR(512) UNIQUE | owner/name |
| html_url | TEXT | GitHub 链接 |
| default_branch | VARCHAR(255) | |
| description | TEXT | |
| primary_language | VARCHAR(255) | |
| stars | INTEGER | |
| forks | INTEGER | |
| watchers | INTEGER | |
| open_issues | INTEGER | |
| size_kb | INTEGER | |
| languages | JSON | `{"Python": 5842000, ...}` |
| topics | JSON | `["python", "fastapi"]` |
| synced_at | DATETIME TZ | |

### 3.2 repository_snapshots — 快照

| 列名 | 类型 | 说明 |
|------|------|------|
| repository_id | INTEGER FK → repositories.id | |
| snapshot | JSON | 完整 RepositorySnapshot |
| synced_at | DATETIME TZ | |

### 3.3 repository_files — 文件列表

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| path | TEXT | 文件路径 |
| category | VARCHAR(64) | FileCategory 枚举值 |
| size | BIGINT | 文件大小 |

### 3.4 repository_file_contents — 源码内容

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| path | TEXT | |
| category | VARCHAR(64) | |
| content | TEXT | 文件源码 |
| size | BIGINT | |
| truncated | BOOLEAN | 是否截断 |
| synced_at | DATETIME TZ | |

### 3.5 issues — Issue 分类结果

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| number | INTEGER | Issue 编号 |
| title | TEXT | |
| state | VARCHAR(64) | open / closed |
| html_url | TEXT | |
| author | VARCHAR(255) | |
| labels | JSON | `["bug", "urgent"]` |
| comments | INTEGER | |
| classification_category | VARCHAR(64) | bug / question / ... |
| classification_confidence | INTEGER | 置信度 × 100 |
| classification | JSON | 完整 IssueClassification |
| created_at / updated_at | DATETIME TZ | |

### 3.6 pull_requests — PR 列表

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| number | INTEGER | |
| title | TEXT | |
| state | VARCHAR(64) | open / closed / merged |
| html_url | TEXT | |
| author | VARCHAR(255) | |
| created_at / updated_at | DATETIME TZ | |

### 3.7 commits — Commit 列表

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| sha | VARCHAR(64) | 前 12 位 |
| message | TEXT | 首行 |
| author | VARCHAR(255) | |
| html_url | TEXT | |
| committed_at | DATETIME TZ | |

### 3.8 knowledge_nodes — RAG 图节点

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| node_key | VARCHAR(512) | "repo", "dir:app", "module:app" |
| node_type | VARCHAR(128) | repository / directory / module / test_suite / test_file / dependency_manifest / documentation |
| name | TEXT | |
| path | TEXT | 对应文件路径 |
| summary | TEXT | |
| metadata_json | JSON | |

### 3.9 knowledge_edges — RAG 图边

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| source_key | VARCHAR(512) | |
| target_key | VARCHAR(512) | |
| relation | VARCHAR(128) | contains / defines_module / tests_with / uses_dependency_manifest / documents |
| metadata_json | JSON | |

### 3.10 knowledge_chunks — RAG 文本块

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| chunk_key | VARCHAR(512) | "chunk:source:app/main.py:0" |
| title | TEXT | "app/main.py source chunk 1" |
| content | TEXT | 源码片段 |
| source_type | VARCHAR(128) | source_code / test / documentation / graph_summary |
| source_path | TEXT | 来源文件路径 |
| node_keys | JSON | 关联节点 key 列表 |
| metadata_json | JSON | focus / path / chunk_index |
| embedding | VECTOR(1536) | pgvector 向量列（仅 PostgreSQL） |

### 3.11 webhook_events — Webhook 事件

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| event_id | VARCHAR(255) UNIQUE | GitHub delivery ID（用于去重） |
| event_type | VARCHAR(64) | "issues" |
| action | VARCHAR(64) | "opened" |
| repository | VARCHAR(512) | "owner/name" |
| issue_number | INTEGER | |
| issue_title | TEXT | |
| issue_state | VARCHAR(64) | |
| issue_labels | JSON | |
| issue_author | VARCHAR(255) | |
| classification_json | JSON | 完整 IssueClassification |
| raw_payload | JSON | 原始 GitHub 请求体 |
| is_read | BOOLEAN | 是否已读 |
| is_deleted | BOOLEAN | 是否已删除 |
| received_at | DATETIME TZ | |

### 3.12 faq_entries — FAQ 知识库

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| question | TEXT | 高频问题 |
| answer | TEXT | 标准回答 |
| keywords | JSON | 关键词列表 |
| related_issue_ids | JSON | 关联 Issue 编号 |
| hit_count | INTEGER | 命中次数 |
| is_confirmed | BOOLEAN | 是否人工确认 |
| embedding | VECTOR(1536) | 向量（用于语义匹配） |
| created_at | DATETIME TZ | |

### 3.13 fix_memory_logs — 长期记忆

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | |
| repository_id | INTEGER FK | |
| issue_title | TEXT | |
| issue_category | VARCHAR(64) | bug / feature_request ... |
| issue_keywords | JSON | 提取的关键词 |
| files_changed | JSON | 修改的文件列表 |
| fix_summary | TEXT | 修复摘要 |
| pattern_type | VARCHAR(128) | null_check / error_handling / refactor / bugfix |
| pattern_detail | TEXT | 详细模式描述 |
| created_at | DATETIME TZ | |

---

## 3.14 表关系图

```
repositories ◄────────────────────────────────────────────┐
  │  id (PK)                                               │
  │  owner, name, full_name                                │
  └────────────────────────────────────────────────────────┘
   │                │               │              │
   │ FK             │ FK            │ FK           │ FK
   ▼                ▼               ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│snapshots │  │  files   │  │contents │  │ issues   │
├──────────┤  ├──────────┤  ├──────────┤  ├──────────┤
│repo_id   │  │repo_id   │  │repo_id   │  │repo_id   │
│snapshot  │  │path,     │  │content   │  │number,   │
│(JSON)    │  │category  │  │,truncated│  │state,    │
└──────────┘  └──────────┘  └──────────┘  │classify  │
                                          └──────────┘
   │                │               │
   │ FK             │ FK            │ FK
   ▼                ▼               ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ pull_req │  │ commits  │  │sync_runs│
├──────────┤  ├──────────┤  ├──────────┤
│repo_id   │  │repo_id   │  │repo_id   │
│number,   │  │sha,      │  │status,   │
│title     │  │message   │  │summary   │
└──────────┘  └──────────┘  └──────────┘

repositories ◄──── 知识图谱 ────► knowledge_*
  │ FK                              │
  │                                 ├── knowledge_nodes
  │                                 │   repo_id, node_key, type
  │                                 ├── knowledge_edges
  │                                 │   repo_id, source, target
  │                                 └── knowledge_chunks
  │                                     repo_id, content, embedding
  │
  ├── faq_entries
  │     repo_id, question, answer, is_confirmed
  │
  ├── fix_memory_logs
  │     repo_id, issue_keywords, files_changed
  │
  └── webhook_events
        event_id (unique), issue_number, classification_json

注: 所有子表通过 repository_id (FK → repositories.id) 关联父表。
```

---

## 四、前端 TypeScript 类型

> 与后端 Pydantic 模型保持手动同步。后端新增字段时需同步更新 `frontend/src/api.ts`。

```typescript
// api.ts 中的核心类型

// 仓库快照
RepositorySnapshot {
  identity: { owner, name, full_name, html_url, default_branch }
  description: string | null
  stats: { stars, forks, watchers, open_issues, size_kb, primary_language, languages }
  topics: string[]
  readme: string | null
  files: ClassifiedFile[]
  file_categories: CategorySummary[]
  issues: GitHubIssue[]
  issue_categories: CategorySummary[]
  pull_requests: PullRequestSummary[]
  recent_commits: CommitSummary[]
  synced_at: string
}

// Issue 分类
IssueClassification {
  category: string         // bug / question / ...
  confidence: number       // 0-1
  reason: string
  suggested_action: string
  signals: string[]
}

GitHubIssue {
  number: number
  title: string
  state: string
  html_url: string
  author: string | null
  labels: string[]
  comments: number
  classification: IssueClassification
  updated_at: string | null
}

// Webhook 事件
WebhookClassification {
  category: string | null
  confidence: number | null
  reason: string | null
  suggested_action?: string | null
  signals?: string[]
  auto_reply_draft?: string | null
}

WebhookEventItem {
  event_id: string
  event_type: string
  action: string
  repository: string
  issue_number: number
  issue_title?: string
  issue_state?: string
  issue_author?: string | null
  issue_labels?: string[]
  classification: WebhookClassification | null
  received_at: string
}

WebhookEventDetail = WebhookEventItem & {
  issue_body: string | null
  issue_comments_count: number
  issue_html_url: string | null
}

// Agent 对话
AssistantChatRequest {
  owner, name: string
  message: string
  freshness?: FreshnessMode
  history?: ChatMessage[]
}

AssistantChatResponse {
  answer: string
  repository: string
  used_cached_data: boolean
  tool_calls: AssistantToolCall[]
  citations: AssistantCitation[]
}
```

---

## 五、关键数据流

### 仓库同步 → 数据库

```
GitHub API JSON → RepositorySyncService
  → Pydantic 模型（RepositorySnapshot）
  → PostgresRepositoryStore.save()
    → _upsert_repository()         → repositories 表
    → _replace_files()             → repository_files 表
    → _replace_file_contents()     → repository_file_contents 表
    → _replace_issues()            → issues 表
    → _replace_pull_requests()     → pull_requests 表
    → _replace_commits()           → commits 表
    → _replace_knowledge_graph()   → knowledge_nodes + edges + chunks 表
    → _record_sync_run()           → sync_runs 表
```

### Webhook 事件 → 前端

```
GitHub Webhook POST → router.py
  → handle_issue_event()
    → async_classify() → IssueClassification
    → WebhookEventRecord
    → webhook_event_store (dict)        ← 内存
    → _persist_event()                   ← PostgreSQL webhook_events 表
  → 前端轮询 GET /events → 显示通知
```

### LLM 分类 → 结构化结果

```
async_classify(title, body, labels)
  ├─ LLM 可用 → 调 AsyncOpenAI
  │   prompt: "Classify this GitHub issue..."
  │   response: {
  │     category: "bug",
  │     confidence: 0.92,
  │     reason: "Matched keywords: crash, traceback",
  │     auto_reply_draft: "感谢反馈..."
  │   }
  └─ LLM 不可用或失败 → 规则降级（关键词匹配）
```

---

## 六、知识图谱构建流程

### 6.1 节点-边-块 三层结构

KnowledgeGraphService.build(snapshot) 一次构建三样东西：

```
┌──────────———————───┐
│ RepositorySnapshot │
│ files / issues /   │
│ source_contents... │
└────────┬────┬──────┘
         │    │
    ┌────┘    └──────────────────┐
    │                            │
    ▼                            ▼
┌──────────────┐        ┌──────────────────┐
│   节点+边     │        │   文本块 (chunks)  │
│              │        │                  │
│ nodes = {    │        │ chunks = [       │
│   "repo"     │        │   overview,      │
│   "dir:app"  │        │   directories,   │
│   "module"   │        │   modules,       │
│   "test"     │        │   deps,          │
│   "dep"      │        │   tests,         │
│   "readme"   │        │   source_chunks  │
│ }            │        │ ]                │
│              │        │                  │
│ edges = [    │        │ 每个 chunk 有     │
│   contains   │        │ node_keys 指向    │
│   defines    │        │ 关联节点           │
│   tests_with │        │                  │
│ ]            │        └──────────────────┘
└──────────────┘
```

### 6.2 节点类型树

```
repository                          ← 仓库根节点
├── contains → directory            ← 顶级目录节点
│   ├── defines_module → module     ← 含源码的目录推断为模块
│   │   └── (tests_module ← test)   ← 测试指向对应模块
│   └── ...
├── uses_dependency_manifest → dependency_manifest  ← 依赖文件
├── tests_with → test_suite         ← 测试套件（按目录分组）
│   └── contains_test → test_file   ← 单个测试文件
└── documents → documentation       ← README
```

### 6.3 构建步骤

```
Step 1: repository node
  1 node, 0 edges
  │
Step 2: directory + module nodes
  N directory nodes + M module nodes
  N+M edges to repo (contains, defines_module)
  │
Step 3: dependency nodes
  K nodes, K edges to repo (uses_dependency_manifest)
  │
Step 4: test suite + file nodes
  P test suites + Q test files
  edges to repo (tests_with) + to modules (tests_module)
  │
Step 5: README node
  1 node, 1 edge (documents)
  │
Step 6: text chunks
  overview_chunks       → 引用所有关键节点
  directory_chunks      → 引用目录节点
  module_chunks         → 引用模块节点
  dependency_chunks     → 引用依赖节点
  test_chunks           → 引用测试节点
  source_content_chunks → 源码滑动窗口切块（不关联节点）
```

### 6.4 搜索路径

```
search("测试在哪")
  ↓ 关键词匹配 or 向量检索
找到 test_chunks
  ↓
通过 chunk.node_keys 找到关联的 test_suite / test_file 节点
  ↓
返回 chunk.content + 关联节点 + 关联边
```


## 七、项目结构分析图构建流程

### 7.1 与知识图谱的区别

| | 知识图谱 | 项目结构分析 |
|--|---------|------------|
| 构建依据 | 源码内容 + 文件分类 | 文件路径 + 依赖文件 |
| 存储 | 数据库（持久化，有向量） | 内存计算（不存储，实时生成） |
| 用途 | Agent RAG 检索 | 前端展示 + 项目理解 |
| 粒度 | 源码行级（chunk） | 文件级 / 依赖级 |
| 输出 | KnowledgeChunk + 节点 | ProjectStructureResponse |

### 7.2 分析流程

```
ProjectAnalysisService.analyze(snapshot)
  │
  ├─ ① 推断项目类型
  │      语言分布 + 文件占比 → 全栈 / Python / Web / ...
  │
  ├─ ② 分析顶级目录
  │      每个目录的文件数 + 主导分类 → top_directories
  │
  ├─ ③ 识别入口文件
  │      main.py / app.py / index.ts / ... → entry_files
  │
  ├─ ④ 解析依赖
  │      requirements.txt → pip 依赖
  │      package.json → npm 依赖
  │      pyproject.toml → 项目元数据
  │      → dependency_packages
  │
  ├─ ⑤ 检测框架
  │      fastapi / django / react / vue → detected_frameworks
  │
  └─ ⑥ 分类统计
         source / test / doc / config / ci → 各类文件列表
```

### 7.3 输出结构

```
ProjectStructureResponse
├── project_type: "Python 后端或工具库项目"
├── source_count: 42
├── dependency_files: [requirements.txt, pyproject.toml]
├── dependency_packages: [
│   { name: "fastapi", ecosystem: "pip", group: "web", source_file: "requirements.txt" }
│ ]
├── detected_frameworks: ["fastapi", "pydantic"]
├── test_files: [test_main.py, ...]
├── doc_files: [README.md, ...]
├── entry_files: [app/main.py]
├── top_directories: [
│   { name: "app", count: 12, main_category: "source_code", source_count: 8 }
│ ]
└── analysis_warning: null
```

### 7.4 前端展示形态

```
┌──────────────────────────────────────────────┐
│  项目结构概览                                  │
│                                              │
│  ┌──────────────────┐  ┌──────────────────┐  │
│  │  技术栈           │  │  目录依赖图        │  │
│  │  Python + FastAPI │  │                   │  │
│  │  42 源码 / 15 测试 │  │  app ─→ main.py  │  │
│  │  5 依赖文件        │  │  │               │  │
│  └──────────────────┘  │  tests ─→ test_   │  │
│                         │  │               │  │
│  ┌──────────────────┐  │  docs ─→ *.md    │  │
│  │  主要目录          │  └──────────────────┘  │
│  │  app · 12 源码    │                        │
│  │  tests · 15 测试   │                        │
│  │  docs · 3 文档     │                        │
│  └──────────────────┘                        │
└──────────────────────────────────────────────┘
```


## 八、存储适配器选择

```
DATABASE_URL 未设置
  └─ InMemoryRepositoryStore（Python dict，重启丢失）

DATABASE_URL = sqlite:///data/issuescope.db
  └─ PostgresRepositoryStore + SQLite
      ├─ 11 张表，跳过 pgvector
      └─ search_knowledge() → 关键词匹配降级

DATABASE_URL = postgresql+psycopg://...
  └─ PostgresRepositoryStore + PostgreSQL
      ├─ 11 张表 + pgvector 向量列
      ├─ CREATE EXTENSION vector
      ├─ IVFFlat 索引（余弦相似度加速）
      └─ search_knowledge() → 向量余弦相似度
```
