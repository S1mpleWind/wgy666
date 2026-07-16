#!/usr/bin/env bash
# ===========================================================================
# IssueScope — 后端初始化脚本
#
# 用法:
#   bash scripts/setup-backend.sh            # 完整初始化（同步依赖 + 检查配置）
#   bash scripts/setup-backend.sh --quick    # 只同步依赖，跳过配置检查
# ===========================================================================

set -euo pipefail
cd "$(dirname "$0")/../backend"

echo "========================================"
echo "  IssueScope — 后端初始化"
echo "========================================"

# ── 1. 检查 uv ───────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "[INFO] 安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.bashrc"
fi
echo "[OK] uv $(uv --version)"

# ── 2. 同步依赖（含 torch CPU 版） ───────────────────────────────────────
echo "[INFO] 安装 Python 依赖（首次会下载 torch CPU 版，可能较慢）..."
uv add torch --index https://download.pytorch.org/whl/cpu
uv sync
echo "[OK] 依赖安装完成"

# ── 3. 验证数据库连接 ─────────────────────────────────────────────────────
echo "[INFO] 检查数据库连接..."
DB_URL="${DATABASE_URL:-$(grep -E '^DATABASE_URL=' .env | cut -d= -f2- || true)}"

if [[ -z "$DB_URL" ]]; then
    echo "[WARN] 未配置 DATABASE_URL。将使用内存存储（数据重启丢失）。"
elif [[ "$DB_URL" == sqlite* ]]; then
    echo "[OK] 使用 SQLite: ${DB_URL/sqlite:\/\//}"
elif [[ "$DB_URL" == postgresql* ]]; then
    echo "[INFO] 测试 PostgreSQL 连接..."
    uv run python3 -c "
from sqlalchemy import create_engine, inspect
e = create_engine('$DB_URL')
insp = inspect(e)
insp.get_table_names()
e.dispose()
print('    连接成功')
" && echo "[OK] PostgreSQL 连接正常" || echo "[WARN] 无法连接 PostgreSQL，请先运行 scripts/setup-db.sh"
fi

# ── 4. 验证关键配置项 ─────────────────────────────────────────────────────
check_config() {
    local key="$1" label="$2"
    if grep -qE "^${key}=" .env 2>/dev/null; then
        echo "[OK] $label 已配置"
    else
        echo "[WARN] $label 未配置（${key}）— 相关功能不可用"
    fi
}

echo "[INFO] 检查环境变量..."
check_config "GITHUB_TOKEN"           "GitHub API 令牌"
check_config "LLM_API_KEY"            "LLM API 密钥"
check_config "GITHUB_WEBHOOK_SECRET"  "Webhook 签名密钥"

# ── 5. 确认本地 embedding 可用性 ──────────────────────────────────────────
if grep -qE '^LOCAL_EMBEDDING_ENABLED=true' .env 2>/dev/null; then
    echo "[INFO] 验证本地 embedding..."
    uv run python3 -c "
try:
    from sentence_transformers import SentenceTransformer
    print('    sentence-transformers 可用')
except ImportError:
    print('    sentence-transformers 未安装，禁用 LOCAL_EMBEDDING_ENABLED')
" 2>/dev/null || echo "    [WARN] embedding 验证跳过"
fi

# ── 6. 完成 ───────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  后端初始化完成"
echo "========================================"
echo ""
echo "启动开发服务器："
echo "  cd backend"
echo "  uv run uvicorn app.main:app --reload --port 8000"
echo ""
echo "运行测试："
echo "  cd backend"
echo "  uv run pytest -v"
echo "========================================"
