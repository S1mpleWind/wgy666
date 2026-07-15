# IssueScope 项目结构与模块依赖文档

> A8 GitHub仓库问答与Issue分析系统
> 版本: 0.1.0

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    前端 (Frontend)                        │
│           React + Vite + TypeScript + Lucide             │
│                port 5173 (dev) / 80 (prod)                │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP (fetch)
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    后端 (Backend)                          │
│              FastAPI + Python 3.12 + uv                    │
│                port 8000 (dev) / 8000 (prod)               │
│                                                           │
│  ┌───────────┐  ┌──────────┐  ┌──────────────────┐      │
│  │ API Routes│  │ Assistant│  │   Webhook          │      │
│  │ (routes/) │  │ (Agent)  │  │   (webhooks/)      │      │
│  └─────┬─────┘  └────┬─────┘  └───────┬──────────┘      │
│        │              │                │                  │
│        ▼              ▼                ▼                  │
│  ┌──────────────────────────────────────────────────┐    │
│  │              Services (业务逻辑层)                  │    │
│  │  github_client  repository_sync  file_classifier  │    │
│  │  issue_classifier  repository_query  project_analysis│  │
│  │  knowledge_graph  embeddings                      │    │
│  └──────────────────────┬───────────────────────────┘    │
│                         │                                 │
│                         ▼                                 │
│  ┌──────────────────────────────────────────────────┐    │
│  │              Storage (数据存储层)                   │    │
│  │  InMemoryRepositoryStore  │  PostgresRepositoryStore │
│  │  (内存, 默认)             │  SQLite/PostgreSQL        │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## 二、后端目录结构详解

```
backend/
├── app/
│   ├── api/routes/          # FastAPI HTTP 路由层
│   │   ├── health.py        #   GET /api/health
│   │   ├── repositories.py  #   POST /sync, GET list/detail
│   │   ├── repository_tools.py  # 文件内容查询
│   │   └── issues.py        #   POST /issues/analyze
│   │
│   ├── assistant/           # LLM 仓库问答智能体
│   │   ├── router.py        #   POST /api/assistant/chat
│   │   ├── harness.py       #   AgentHarness: LLM 工具调用循环
│   │   ├── tool_registry.py #   7 个工具的 OpenAI function-calling 定义
│   │   └── tools.py         #   工具实现 (overview, search_files 等)
│   │
│   ├── webhooks/            # 🔔 GitHub Webhook（你的模块）
│   │   ├── router.py        #   POST /github, GET /events, GET /events/{id}, GET /config
│   │   ├── handler.py       #   签名验证 + 事件分发 + Issue 处理
│   │   └── auto_reply.py    #   LLM 自动回复生成
│   │
│   ├── schemas/             # Pydantic v2 模型（前后端 API 契约）
│   │   ├── repository.py    #   RepositorySnapshot, ClassifiedFile 等
│   │   ├── issue.py         #   IssueCategory, IssueClassification
│   │   ├── assistant.py     #   Chat request/response, FreshnessMode
│   │   ├── project_analysis.py  # 项目结构分析结果
│   │   ├── repository_tools.py  # 查询工具响应模型
│   │   └── knowledge.py     #   KnowledgeNode/Edge/Chunk/SearchResult
│   │
│   ├── services/            # 无状态业务逻辑
│   │   ├── github_client.py     # HTTPX 异步 GitHub REST API 客户端
│   │   ├── repository_sync.py   # 同步编排：拉取→分类→组装快照
│   │   ├── repository_url.py    # GitHub URL 解析 → RepositoryRef
│   │   ├── repository_query.py  # 查询门面（缓存/刷新策略）
│   │   ├── file_classifier.py   # 文件规则分类（10 类）
│   │   ├── issue_classifier.py  # Issue 规则分类（9 类 + UNKNOWN）
│   │   ├── project_analysis.py  # 项目结构分析
│   │   ├── knowledge_graph.py   # 图结构 RAG 构建 + 关键词检索
│   │   └── embeddings.py        # 文本→向量（OpenAI API / 哈希回退）
│   │
│   ├── storage/             # 数据存储适配器
│   │   ├── __init__.py      #   按 DATABASE_URL 选择存储后端
│   │   ├── memory.py        #   内存存储（默认，重启丢失）
│   │   ├── postgres.py      #   SQLite/PostgreSQL 持久化存储
│   │   └── database.py      #   SQLAlchemy 表定义 + pgvector
│   │
│   └── core/
│       └── config.py        # Pydantic-settings 配置（所有环境变量）
│
├── tests/                   # 测试
│   ├── test_webhooks/       #   Webhook 模块测试 (44 个)
│   ├── test_assistant/      #   Agent 测试（需 LLM_API_KEY）
│   ├── test_services/       #   服务层测试（embeddings, sync, tools）
│   └── test_project_analysis.py
│
├── data/                    # SQLite 数据库文件（本地开发）
│   └── issuescope.db
├── .env                     # 环境变量（不提交）
├── pyproject.toml           # 依赖管理
└── CLAUDE.md                # 项目文档（已废弃，以本文档为准）
```

---

## 三、前端目录结构

```
frontend/
├── src/
│   ├── main.tsx             # React 入口
│   ├── App.tsx              # 主应用（表单 + 仪表盘 + 通知 + Issue详情 + 聊天）
│   ├── App.css              # 全部样式
│   ├── api.ts               # HTTP 客户端 + TypeScript 类型定义
│   └── ProjectStructureDetails.tsx  # 项目结构详情组件
├── index.html
├── package.json
└── vite.config.ts
```

---

## 四、模块依赖关系

### 4.1 API 路由 → Service 调用关系

```
POST /api/repositories/sync
  → RepositorySyncService.sync()
    → GitHubClient.get_repository() / get_tree() / get_issues() ...
    → FileClassifier.classify_many()
    → IssueClassifier.classify() / summarize()

POST /api/assistant/chat
  → AgentHarness.answer()
    → RepositoryQueryService.get_snapshot()
    → AsyncOpenAI chat.completions.create()
    → RepositoryToolRegistry.execute()
      → RepositoryAssistantTools.*()
        → RepositoryQueryService / ProjectAnalysisService / KnowledgeGraphService

POST /api/webhooks/github
  → dispatch_event() → handle_issue_event()
    → IssueClassifier.classify()
  → IssueAutoReplyService.generate_reply()
    → RepositoryQueryService.get_snapshot()
    → AsyncOpenAI chat.completions.create()
    → GitHubClient.comment_on_issue()

GET /api/webhooks/events/{id}
  → 直接读 webhook_event_store dict

GET /api/repositories/{owner}/{name}/tools/file-contents
  → repository_store.get_file_contents()
```

### 4.2 存储层选择逻辑

```
storage/__init__.py
  │
  ├─ DATABASE_URL 未设置? → InMemoryRepositoryStore（内存）
  │
  └─ DATABASE_URL 已设置?
      ├─ postgresql:// → PostgresRepositoryStore（PG + pgvector）
      └─ sqlite:///    → PostgresRepositoryStore（SQLite，跳过向量）
```

### 4.3 关键数据流

```
仓库同步流:
  GitHub REST API
    → GitHubClient (httpx)
    → RepositorySyncService
    → RepositorySnapshot (Pydantic)
    → repository_store.save()

Webhook 事件流:
  GitHub Webhook (POST)
    → router.py (HMAC 验证)
    → handler.py (IssueClassifier 分类)
    → webhook_event_store[] (内存)
    → IssueAutoReplyService (LLM 回复)
    → GitHubClient.comment_on_issue()

Agent 问答流:
  用户问题
    → AgentHarness (LLM 工具循环)
    → RepositoryToolRegistry (7 个工具)
    → RepositorySnapshot (缓存数据)
    → AsyncOpenAI → 回答

RAG 知识图谱流:
  RepositorySnapshot
    → KnowledgeGraphService.build()
      → nodes (repo/dir/module/dep/test)
      → edges (contains/defines/tests)
      → chunks (源码分块 + 图摘要)
    → EmbeddingService.embed_texts()  [pgvector 模式]
    → knowledge_chunks 表
    → search() / search_knowledge()  [关键词 / 向量检索]
```

---

## 五、测试体系

```
tests/
├── test_webhooks/              # 44 个测试，覆盖你的模块全部功能
│   ├── test_router.py          #   HTTP 端点（签名、事件列表、事件详情）
│   ├── test_handler.py         #   签名验证、分类逻辑、事件存储
│   ├── test_auto_reply.py      #   自动回复服务（无 LLM 时优雅降级）
│   └── test_github_client.py   #   客户端方法签名验证
│
├── test_services/              # 服务层测试
│   ├── test_embeddings.py      #   哈希回退 embedding
│   ├── test_knowledge_graph.py #   RAG 构建+搜索（中文别名）
│   ├── test_repository_tools.py #  文件内容查询
│   └── test_repository_sync.py #   同步过滤逻辑
│
├── test_assistant/
│   └── test_router.py          # Agent 端点测试（需 LLM_API_KEY）
│
└── test_project_analysis.py    # 项目结构分析
```

---

## 六、配置项说明

| 环境变量 | 默认值 | 用途 | 必需 |
|----------|--------|------|------|
| `GITHUB_TOKEN` | — | GitHub API 认证（提高限速到 5000/h） | 推荐 |
| `GITHUB_WEBHOOK_SECRET` | — | Webhook HMAC-SHA256 签名密钥 | webhook |
| `LLM_API_KEY` | — | OpenAI 兼容 LLM API 密钥 | agent |
| `LLM_API_BASE_URL` | `https://models.sjtu.edu.cn/api/v1` | LLM API 地址 | 否 |
| `LLM_MODEL` | `deepseek-reasoner` | LLM 模型名 | 否 |
| `DATABASE_URL` | — | `sqlite:///data/issuescope.db` 或 `postgresql://...` | 持久化 |
| `EMBEDDING_API_KEY` | — | Embedding API 密钥（无则哈希回退） | 高精度RAG |

---

## 七、组员模块边界

| 负责人 | 模块 | 依赖上游 | 被谁依赖 |
|--------|------|---------|---------|
| **jyf（你）** | webhooks/ | IssueClassifier | 前端通知 |
| **jyf** | github_client 写操作 | GitHub API | auto_reply → 发评论 |
| **ykz** | assistant/（Harness + Tools） | RepositoryQueryService, KnowledgeGraphService | 前端聊天面板 |
| **ykz** | storage/postgres.py | database.py（SQLAlchemy） | API routes |
| **yjq** | knowledge_graph.py | EmbeddingService | Agent 的 knowledge_graph_search 工具 |
| **yjq** | embeddings.py | OpenAI API | knowledge_graph + postgres |

---

## 八、技术栈依赖

```
Python 3.12
├── FastAPI              Web 框架
├── uvicorn              ASGI 服务器
├── httpx                异步 HTTP 客户端（→ GitHub REST API）
├── openai               OpenAI SDK（→ LLM Agent）
├── sqlalchemy           ORM（→ SQLite / PostgreSQL）
├── psycopg              PostgreSQL 驱动（仅 PG 模式需要）
├── pydantic-settings    环境变量管理
└── pytest + pytest-asyncio  测试框架

Node.js / TypeScript
├── React                UI 框架
├── Vite                 构建工具
├── lucide-react         图标库
├── react-markdown       Markdown 渲染
└── remark-gfm           Markdown GFM 扩展
```
