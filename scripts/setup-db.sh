#!/usr/bin/env bash
# ===========================================================================
# IssueScope — 数据库初始化脚本
#
# 用法:
#   bash scripts/setup-db.sh               # 启动 PostgreSQL（已有 docker 时）
#   bash scripts/setup-db.sh --reset       # 删除旧数据重新开始
# ===========================================================================

set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.yml"
DB_CONTAINER="issuescope-postgres"

# ── 检查 Docker ───────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[ERROR] Docker 未安装。请先安装 Docker："
    echo "  curl -fsSL https://get.docker.com | sh"
    exit 1
fi

# ── 镜像源配置 ─────────────────────────────────────────────────────────────
configure_mirror() {
    local daemon_file="/etc/docker/daemon.json"
    echo ""
    echo "[询问] 是否配置 Docker 镜像加速器？（中国大陆访问 Docker Hub 可能不稳定）"
    echo "  1) 不配置（直接连接 Docker Hub）"
    echo "  2) 配置镜像 https://docker.1ms.run（推荐）"
    echo "  3) 自定义镜像地址"
    read -r -p "  请选择 [1/2/3] (默认 1): " mirror_choice
    mirror_choice="${mirror_choice:-1}"

    case "$mirror_choice" in
        2) MIRROR_URL="https://docker.1ms.run" ;;
        3) read -r -p "  输入镜像地址: " MIRROR_URL ;;
        *) echo "[SKIP] 跳过镜像配置" ;;
    esac

    if [[ -n "${MIRROR_URL:-}" ]]; then
        echo "[INFO] 配置 Docker 镜像源: $MIRROR_URL"
        if [[ -f "$daemon_file" ]]; then
            # 已有配置文件，追加镜像
            sudo sed -i "s|\"registry-mirrors\": \[[^]]*\]|\"registry-mirrors\": [\"$MIRROR_URL\"]|" "$daemon_file" 2>/dev/null || {
                # sed 失败则重新生成
                local content
                content=$(cat "$daemon_file")
                echo "$content" | python3 -c "
import json,sys
cfg=json.load(sys.stdin)
cfg.setdefault('registry-mirrors',[])
if '$MIRROR_URL' not in cfg['registry-mirrors']:
    cfg['registry-mirrors'].insert(0,'$MIRROR_URL')
json.dump(cfg,sys.stdout,indent=2)
" | sudo tee "$daemon_file" >/dev/null
            }
        else
            echo "{\"registry-mirrors\":[\"$MIRROR_URL\"]}" | sudo tee "$daemon_file" >/dev/null
        fi
        sudo systemctl restart docker
        echo "[OK] 镜像源已配置，Docker 已重启"
    fi
}

# ── 重置 ───────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--reset" ]]; then
    echo "[INFO] 停止并删除旧容器、旧数据..."
    docker-compose -f "$COMPOSE_FILE" down -v
    echo "[OK] 已清理"
fi

# ── 配置镜像源 ─────────────────────────────────────────────────────────────
configure_mirror

# ── 启动 PostgreSQL ───────────────────────────────────────────────────────
echo "[INFO] 启动 PostgreSQL (pgvector/pg16)..."
docker-compose -f "$COMPOSE_FILE" up -d

# ── 等待就绪 ──────────────────────────────────────────────────────────────
echo "[INFO] 等待数据库就绪..."
for i in $(seq 1 30); do
    if docker exec "$DB_CONTAINER" pg_isready -U issuescope -d issuescope &>/dev/null; then
        echo "[OK] 数据库已就绪 (localhost:5432)"
        break
    fi
    if [[ "$i" -eq 30 ]]; then
        echo "[ERROR] 数据库启动超时，请检查日志：docker-compose logs postgres"
        exit 1
    fi
    sleep 1
done

# ── 验证 pgvector ─────────────────────────────────────────────────────────
echo "[INFO] 验证 pgvector 扩展..."
docker exec "$DB_CONTAINER" psql -U issuescope -d issuescope -c "
    CREATE EXTENSION IF NOT EXISTS vector;
" >/dev/null
echo "[OK] pgvector 已就绪"

# ── 输出连接信息 ───────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  数据库连接信息"
echo "========================================"
echo "  Host:     localhost"
echo "  Port:     5432"
echo "  User:     issuescope"
echo "  Password: issuescope"
echo "  Database: issuescope"
echo "  URL:      postgresql+psycopg://issuescope:issuescope@localhost:5432/issuescope"
echo ""
echo "  在 backend/.env 中设置 DATABASE_URL 使用此连接。"
echo "========================================"
