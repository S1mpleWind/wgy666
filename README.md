# IssueScope

IssueScope 是一款面向开源项目维护者和开发团队的 GitHub 仓库问答与 Issue 分析系统。系统同步 GitHub 仓库中的代码、README、Issue、Pull Request 和提交记录，结合规则分析、源码关系解析、RAG 与大模型工具调用，帮助开发者快速理解项目、定位问题并处理 Issue。

## 核心功能

- **GitHub 仓库接入：** 输入公开仓库地址，统一同步仓库信息、目录树、文件、Issue、Pull Request 和提交记录。
- **项目结构解析：** 自动识别源码模块、依赖文件、入口文件、测试、文档和 CI/CD 配置，并生成可交互的架构视图。
- **仓库智能问答：** 支持 What、Where、How 类型问题，通过仓库检索与工具调用生成带引用依据的回答。
- **Issue 智能分析：** 识别缺陷、功能请求、使用咨询、重复问题和信息不足等类型，并生成分析理由与回复建议。
- **Issue 自动监听：** 通过 GitHub Webhook 接收新 Issue 事件，在工作台中查看和处理。
- **FAQ 知识库：** 管理高频问题，并根据已有 Issue 生成 FAQ 候选内容。
- **源码关系分析：** 展示源码语义关系、变更影响、建议回归测试、架构健康度和版本演化。
- **自动修复原型：** 结合 Issue 与仓库上下文生成修复方案，在独立分支提交修改并发起 Pull Request，不直接修改主分支。

## 项目优点

- **一站式仓库工作台：** 将仓库浏览、项目解析、Issue 分析、智能问答和 FAQ 集中在同一套 Web 界面中。
- **AI 与规则分析结合：** 项目目录、依赖和源码关系使用确定性规则解析，复杂问答和回复生成由大模型辅助完成。
- **分析结果可追溯：** 智能问答保留工具调用记录和文件引用，减少无依据回答。
- **面向真实维护流程：** 支持 GitHub API、Webhook、分支和 Pull Request，能够接入实际开源项目工作流。
- **数据可持久化：** 支持 PostgreSQL 与 pgvector，也可使用内存存储快速体验。
- **前后端分离：** 模块职责清晰，便于四个功能方向并行开发和后续扩展。

## 技术栈

- **前端：** React 19、TypeScript、Vite、XYFlow、Lucide Icons
- **后端：** Python 3.12、FastAPI、Pydantic、HTTPX、OpenAI SDK
- **数据库：** PostgreSQL 16、pgvector、SQLAlchemy
- **知识检索：** 文档切分、Embedding、向量检索、知识图谱
- **依赖管理：** 后端使用 `uv`，前端使用 `npm`

## 项目目录

```text
wgy666/
├── backend/              # 当前 FastAPI 后端
│   ├── app/              # API、服务、存储、智能体和 Webhook
│   ├── tests/            # 后端自动化测试
│   ├── scripts/          # 质量评估与并发测试脚本
│   └── evaluation/       # 问答评估样例
├── frontend/             # 当前 React 前端
├── UIprototype/          # 界面原型迭代成果
├── TechPrototype/        # 技术原型迭代成果与归档代码
├── docs/                 # 架构、接口、部署和质量文档
├── scripts/              # 环境与端到端测试脚本
└── docker-compose.yml    # PostgreSQL/pgvector 开发环境
```

日常开发和启动使用根目录的 `backend/` 与 `frontend/`。`TechPrototype/code/` 用于保存技术原型迭代归档。

## 环境要求

- Git
- Python 3.12 或更高版本
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 或更高版本
- Docker Desktop（使用 PostgreSQL 时需要）

## 配置后端

在 `backend/` 目录创建 `.env` 文件：

```dotenv
DATABASE_URL=postgresql+psycopg://issuescope:issuescope@127.0.0.1:5432/issuescope

GITHUB_TOKEN=
GITHUB_WEBHOOK_SECRET=

LLM_API_BASE_URL=https://models.sjtu.edu.cn/api/v1
LLM_API_KEY=
LLM_MODEL=deepseek-reasoner

EMBEDDING_API_BASE_URL=https://models.sjtu.edu.cn/api/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-3-small
```

- `GITHUB_TOKEN` 用于提高 GitHub API 限额，并支持创建分支和 Pull Request。
- `LLM_API_KEY` 用于仓库问答、Issue 回复和自动修复。
- `GITHUB_WEBHOOK_SECRET` 用于验证 GitHub Webhook 请求。
- 不配置 `DATABASE_URL` 时，后端会使用内存存储，重启后数据不会保留。

不要将真实 Token 或 API Key 提交到 Git 仓库。

## 启动项目

### 1. 启动 PostgreSQL

在项目根目录执行：

```bash
docker compose up -d postgres
```

### 2. 启动后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

后端启动后可访问：

- API：`http://127.0.0.1:8000`
- Swagger 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

### 3. 启动前端

打开另一个终端：

```bash
cd frontend
npm install
npm run dev -- --port 5173
```

浏览器访问：

```text
http://127.0.0.1:5173
```

前端默认连接 `http://127.0.0.1:8000`。后端部署在其他地址时，可在启动前设置：

```bash
export VITE_API_BASE_URL="http://服务器地址:8000"
```

Windows PowerShell 使用：

```powershell
$env:VITE_API_BASE_URL="http://服务器地址:8000"
```

## 基本使用

1. 在首页输入 GitHub 仓库 URL，并设置同步数量。
2. 同步完成后，在仓库概览查看项目统计、文件和 Issue。
3. 进入项目解析，查看目录、依赖、测试、源码架构和变更影响。
4. 在仓库问答中询问项目结构、代码位置、使用方式或测试方法。
5. 在 Issue 智能分析中查看同步 Issue 和 Webhook 事件，生成分类与回复建议。
6. 在 FAQ 知识库中维护高频问题。

## Webhook 地址

部署后端后，在 GitHub 仓库的 `Settings -> Webhooks` 中填写：

```text
http://服务器地址:8000/api/webhooks/github
```

GitHub 中填写的 Secret 必须与后端的 `GITHUB_WEBHOOK_SECRET` 一致，建议订阅 Issues 事件。

## 测试

后端测试：

```bash
cd backend
uv run pytest
```

前端检查：

```bash
cd frontend
npm run lint
npm run build
```
