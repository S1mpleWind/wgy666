# IssueScope 测试文档

> 系统测试结构、覆盖范围和运行方式。

---

## 测试概览

全部测试：**60+ 个**，覆盖 webhook、服务层、分类器、FAQ、并发场景。

| 目录 | 数量 | 说明 |
|------|------|------|
| `test_webhooks/` | 50+ | Webhook 接收、签名、事件存储、回复、修复、并发 |
| `test_services/` | 15+ | Issue 分类、embedding、FAQ、自动修复、知识图谱 |
| `test_assistant/` | 3+ | Agent 工具调用（需 LLM_API_KEY） |
| `test_project_analysis.py` | 3 | 项目结构分析 |
| `test_storage/` | 1 | PostgreSQL 存储 |

### 运行方式

```bash
cd backend

# 全部测试
uv run pytest -v

# 仅 Webhook 模块
uv run pytest tests/test_webhooks/ -v

# 按名称筛选
uv run pytest -k "test_handle_bug" -v
```

---

## Webhook 测试（`test_webhooks/`）

### `test_handler.py` — 事件处理核心

| 测试 | 验证 |
|------|------|
| `test_verify_signature_*` (×5) | HMAC 签名验证：无 secret 跳过、缺头拒绝、前缀错误、正确签名、错误签名 |
| `test_handle_bug_issue` | Bug 类型 Issue 分类为 BUG |
| `test_handle_question_issue` | 咨询类型分类为 QUESTION |
| `test_handle_issue_ignores_non_opened` | opened/closed/reopened 处理，edited/labeled 忽略 |
| `test_handle_issue_missing_repo` | 缺仓库信息返回 None |
| `test_handle_issue_empty_body` | 空 body 降级为 INFO_NEEDED |
| `test_stores_event_in_memory` | 事件写入 webhook_event_store |
| `test_dispatch_*` | 事件分发路由正确、未知事件忽略 |
| `test_record_creation` | WebhookEventRecord dataclass 创建 |

### `test_router.py` — HTTP 端点

| 测试 | 验证 |
|------|------|
| `test_post_github_webhook_dev_mode` | 无 secret 时正常接收 |
| `test_post_webhook_missing_event_header` | 缺 X-GitHub-Event → 422 |
| `test_post_webhook_invalid_json` | 非 JSON → 400 |
| `test_post_webhook_*_signature` | 签名验证：正确→200，错误→400，缺头→400 |
| `test_list_events_*` | 事件列表：空、含数据、limit 参数、仓库过滤 |
| `test_get_event_detail_*` | 事件详情：存在、不存在、分类字段完整 |
| `test_approved_reply_is_posted_*` | 确认回复自动发布 |

### `test_concurrency.py` — 并发与压力测试

| 测试 | 验证 |
|------|------|
| `test_rapid_webhooks_same_repo` | 10 个快速事件发到同一仓库，全部存储 |
| `test_interleaved_read_write` | 写入中间穿插读取，不冲突 |
| `test_dedup_by_delivery_id` | 同一 delivery_id 不重复计算 |
| `test_missing_event_header_422` | 缺事件头返回 422 |

### `test_auto_reply.py` — 自动回复服务

| 测试 | 验证 |
|------|------|
| `test_generate_reply_returns_none_when_llm_not_configured` | 无 LLM key 时优雅降级 |
| `test_generate_reply_graceful_on_api_failure` | API 失败时静默处理 |
| `test_propose_fix_pr_returns_none` | PR 提议桩函数 |
| `test_service_initialization` | 根据 LLM_API_KEY 初始化 |

### `test_github_client.py` — GitHub API 客户端

| 测试 | 验证 |
|------|------|
| `test_client_can_be_imported` | 客户端可导入 |
| `test_error_has_status_code` | 错误对象有状态码 |
| `test_get_readme_returns_none_on_404` | 404 时返回 None |
| `test_*_signature` (×6) | 各方法签名正确 |
| `test_create_or_update_file_*` | 文件写入 API（base64 编码、可选 sha） |
| `test_comment_on_issue_builds_correct_path` | 评论路径拼接正确 |

---

## 服务层测试（`test_services/`）

### `test_issue_classifier.py` — Issue 分类

| 测试 | 验证 |
|------|------|
| `test_classify_*_by_keyword` (×2) | bug/question 关键词匹配 |
| `test_classify_unknown_when_no_match` | 无匹配返回 UNKNOWN |
| `test_classify_empty_body_gets_info_needed` | 空 body 降级 |
| `test_classify_labels_get_double_weight` | 标签匹配双倍权重 |
| `test_classify_returns_signals` | 返回信号列表 |
| `test_async_classify_*` (×3) | 异步分类降级 + LLM 兜底 |

### `test_embeddings.py` — 向量嵌入

| 测试 | 验证 |
|------|------|
| `test_hash_embedding_*` (×3) | 哈希 embedding 确定性、差异性、单位向量 |
| `test_embed_texts_empty` | 空输入返回空列表 |
| `test_embed_texts_multiple` | 多文本返回多向量 |

### `test_faq_memory.py` — FAQ 与记忆（需 DB）

| 测试 | 验证 |
|------|------|
| `test_faq_crud_is_scoped_to_repository` | FAQ CRUD 按仓库隔离 |
| `test_faq_matching_does_not_cross_repositories` | FAQ 匹配不跨仓库 |
| `test_fix_memory_is_persisted_and_scoped` | 修复记忆持久化 |
| `test_faq_rows_always_have_repository_id` | FAQ 始终有 repository_id |

### `test_faq_generate.py` — FAQ 自动生成

| 测试 | 验证 |
|------|------|
| `test_faq_generate_reason_no_issues` | 无 closed Issue 时返回 reason |
| `test_faq_generate_reason_insufficient` | 不足聚类时返回 reason |

### `test_auto_fix.py` — 自动修复

| 测试 | 验证 |
|------|------|
| `test_fix_issue_returns_unsuccessful` | 管线未实现时返回错误 |
| `test_fix_issue_returns_error_when_no_llm` | 无 LLM 时返回配置错误 |
| `test_fix_proposal_dataclass` | FixProposal/FixFileChange 结构正确 |

### `test_git_clone_security.py` — Git 克隆安全

| 测试 | 验证 |
|------|------|
| `test_clone_url_does_not_leak_token_in_logs` | Token 不在日志中暴露 |
| `test_clone_rejects_invalid_repository_url` | 无效 URL 被拒绝 |
| `test_temp_directory_is_cleaned_on_failure` | 失败时临时目录被清理 |

### `test_knowledge_graph.py` — 知识图谱

| 测试 | 验证 |
|------|------|
| `test_knowledge_graph_builds_structure_dependency_and_test_chunks` | 图谱构建含结构、依赖、测试块 |
| `test_knowledge_graph_search_supports_chinese_focus_terms` | 中文别名搜索 |

### `test_repository_sync.py` — 仓库同步

| 测试 | 验证 |
|------|------|
| `test_source_content_filtering_excludes_assets` | 过滤 ASSET/DATA 文件 |
| `test_source_content_filtering_respects_size_limit` | 超大小文件被过滤 |

### `test_repository_tools.py` — 仓库工具

| 测试 | 验证 |
|------|------|
| `test_get_file_contents_empty_when_not_synced` | 未同步返回空 |
| `test_get_file_contents_returns_source_files` | 返回源码内容 |
| `test_get_file_content_by_path` | 按路径查询 |
| `test_get_file_content_nonexistent_path` | 不存在路径返回 None |

### `test_repository_api.py` — 仓库 API

| 测试 | 验证 |
|------|------|
| `test_list_repositories_returns_empty_when_none_synced` | 空列表 |
| `test_sync_store_and_retrieve` | 同步后能取出 |

---

## 运行说明

- **Webhook 测试**不需要外部依赖，使用 in-memory 存储
- **Assistant 测试**需要 `LLM_API_KEY` 配置，无 key 时自动跳过
- **FAQ 记忆测试**使用 SQLite（临时文件），不依赖 PostgreSQL
- **并发测试**使用同步 TestClient 模拟快速请求

```bash
# 全部测试（跳过需要 LLM key 的）
cd backend
uv run pytest -v -m "not requires_llm" 2>/dev/null || uv run pytest -v

# 只看 webhook
uv run pytest tests/test_webhooks/ -v

# 只看服务和分类器
uv run pytest tests/test_services/ -v
```
