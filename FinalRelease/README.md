# IssueScope 最终交付说明

IssueScope 是面向开源项目维护者和开发团队的 GitHub 仓库问答与 Issue 分析系统。系统能够同步仓库代码、README、Issue、Pull Request 和提交记录，并提供项目结构解析、仓库问答、Issue 分类、Webhook 监听、FAQ 管理和自动修复原型等功能。

## 交付内容

```text
FinalRelease/
├── documents/          # Vision、软件架构、UML 模型和项目总结报告
├── presentation/       # 验收答辩 PPT
├── code/               # 后端、前端源代码和前端生产构建结果
├── unit-tests/         # 单元测试代码与覆盖率报告
├── system-tests/       # 系统功能、易用性、兼容性和性能测试用例
└── iteration-records/  # 三个迭代的计划、评估及补充设计材料
```

`documents/IssueScope-UML模型.docx` 包含用例模型、分析模型和设计模型。前端可执行构建位于 `code/frontend/dist/`；后端为 Python 可直接运行项目，入口为 `code/backend/app/main.py`。

## 技术环境

- Python 3.12、FastAPI、Pydantic、SQLAlchemy
- React 19、TypeScript、Vite
- PostgreSQL、pgvector
- 后端依赖使用 `uv` 管理，前端依赖使用 `npm` 管理

## 启动方式

### 1. 启动数据库（可选）

在 `code/` 目录执行：

```bash
docker compose up -d postgres
```

未配置 PostgreSQL 时，后端会使用内存存储，适合本地界面演示。

### 2. 启动后端

```bash
cd code/backend
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

GitHub Token、Webhook Secret、模型地址和模型密钥在 `.env` 中配置，不要将真实密钥提交到仓库。

### 3. 启动前端

开发模式：

```bash
cd code/frontend
npm ci
npm run dev -- --port 5173
```

浏览器访问 `http://127.0.0.1:5173`。生产构建已保存在 `code/frontend/dist/`。

## 测试结果

- 后端回归测试：171 项通过；真实数据库与模型集成补测 5 项通过。
- Issue 分类子系统单元测试：16 项通过，语句覆盖率 97.47%。
- 前端组件测试：7 项通过，静态检查和生产构建通过。
- 系统测试：37 条全部通过，包括功能测试 26 条、易用性测试 4 条、兼容性测试 4 条和性能测试 3 条。

详细覆盖率报告位于 `unit-tests/reports/`，系统测试步骤和执行结果位于 `system-tests/IssueScope-系统测试用例.xlsx`。
