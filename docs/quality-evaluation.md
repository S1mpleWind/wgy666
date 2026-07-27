# 问答质量与并发测试

这两类测试需要连接正在运行的后端，生成的结果保存在 `backend/evaluation/results/`，不会提交到 Git。

## 一、仓库问答质量采样

题库位于 `backend/evaluation/qa_cases.json`，目前包含 What、Where、How、Issue、工程和风险六类问题。每条问题给出预期事实、预期引用文件和禁止出现的错误表述。

先检查题库格式，不调用模型：

```bash
cd backend
uv run python scripts/evaluate_assistant.py --validate-only
```

后端启动且目标仓库已同步后运行完整评估：

```bash
uv run python scripts/evaluate_assistant.py \
  --owner wgy2006 \
  --name wgy666 \
  --runs 3
```

调试时可只运行前两题，避免浪费模型额度：

```bash
uv run python scripts/evaluate_assistant.py --case-limit 2 --runs 1
```

脚本自动统计事实关键词覆盖率、引用文件命中率、错误表述、响应时间和多次回答波动。自动分数只能用于初筛，最终报告还需要两名成员按准确性、完整性和清晰度分别打分。

## 二、并发测试

普通测试中的 `test_webhooks/test_concurrency.py` 使用 `AsyncClient` 同时发送请求，并额外验证路由中同时存在多个在途请求：

```bash
cd backend
uv run pytest tests/test_webhooks/test_concurrency.py -v
```

实际性能数据使用正在运行的后端测量。先测服务和数据库读取，再测模型调用：

```bash
# 服务基线
uv run python scripts/load_test.py health --requests 100 --concurrency 20

# 已同步仓库的数据库读取与序列化
uv run python scripts/load_test.py repository \
  --owner wgy2006 --name wgy666 \
  --requests 100 --concurrency 10

# Webhook 接收；配置 secret 时脚本会读取 GITHUB_WEBHOOK_SECRET
uv run python scripts/load_test.py webhook --requests 50 --concurrency 10

# 真实 LLM 路径，建议从低并发开始，避免额度消耗
uv run python scripts/load_test.py assistant \
  --owner wgy2006 --name wgy666 \
  --requests 8 --concurrency 2
```

建议按以下档位分别测试，并保持服务器、数据库、模型和网络条件一致：

| 测试对象 | 并发档位 | 建议请求数 |
|---|---|---:|
| health | 1、10、20、50 | 每档 100 |
| repository | 1、5、10、20 | 每档 100 |
| webhook | 1、5、10、20 | 每档 50 |
| assistant | 1、2、4、8 | 每档 8～16 |

报告会记录成功率、吞吐量、平均耗时、P50、P95、P99、最大耗时和状态码分布。最终迭代评估报告应填写实际测量结果，不使用预估数据。

## 三、回答中的代码引用

问答返回文件类型引用时，前端将文件路径显示为可点击按钮。点击后会通过现有文件内容接口打开源码弹窗；若后端未来返回 `line_start` 和 `line_end`，弹窗会自动高亮对应行。数据库中没有该文件内容时，可使用弹窗右上角的 GitHub 链接查看原文件。
