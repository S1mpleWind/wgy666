# GitHub Issue Analysis Platform

一个用于拉取 GitHub 仓库信息、分类仓库内容并展示 Issue 分析结果的前后端分离项目骨架。

当前版本聚焦后续开发的基石：

- Python FastAPI 后端，使用 `uv` 管理依赖。
- React + Vite + TypeScript 前端，使用 `npm` 管理依赖。
- 支持输入公开 GitHub 仓库链接并同步仓库元信息、README、目录树、Issue、PR、提交记录。
- 使用规则分类器完成初版文件分类和 Issue 分类。
- 默认可用内存存储快速开发；配置 `DATABASE_URL` 后会使用 PostgreSQL 持久化主业务数据，并已预留 pgvector 扩展给后续 RAG。

## 运行后端

首次使用数据库时先启动 PostgreSQL：

```powershell
docker compose up -d postgres
```

```powershell
cd backend
$env:DATABASE_URL="postgresql+psycopg://wgy666:wgy666@127.0.0.1:5432/wgy666"
uv run uvicorn app.main:app --reload --port 8000
```

可选：设置 GitHub token 提高 API 速率限制。

```powershell
$env:GITHUB_TOKEN="ghp_xxx"
```

## 运行前端

```powershell
cd frontend
npm install
npm run dev
```

前端默认请求 `http://localhost:8000`。如需修改：

```powershell
$env:VITE_API_BASE_URL="http://localhost:8000"
```

## 目录

```text
backend/
  app/
    api/routes/       # HTTP 接口
    core/             # 配置
    schemas/          # API 数据模型
    services/         # GitHub 拉取、分类等业务逻辑
    storage/          # 存储适配层，支持内存和 PostgreSQL
frontend/
  src/
    api.ts            # 前端 API client 与类型
    App.tsx           # 当前最小展示界面
docs/
  ai-prompts.md       # AI 协作提示词记录
```

## 后续扩展建议

- 在 PostgreSQL 上继续扩展 RAG 知识库表和 pgvector embedding 索引。
- 为同步流程引入 Celery/Redis，避免大仓库同步阻塞 HTTP 请求。
- 在 `app/services` 下新增知识库构建、文档切分、向量检索和 LLM 问答服务。
- 将 `IssueClassifier` 从规则分类升级为“规则初筛 + LLM 复核”的可解释分类流程。
