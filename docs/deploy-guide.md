# 后端部署文档

## 前提

- 一台 Ubuntu/Debian 服务器（公网可达）
- GitHub Personal Access Token（可选但推荐，提高 API 频率限制）
- 项目代码

---

## 1. 服务器环境准备

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Python 依赖（uv 需要）
sudo apt install -y curl git build-essential
```

---

## 2. 安装 uv（Python 包管理）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.bashrc

# 验证安装
uv --version
```

---

## 3. 部署后端应用

```bash
# 拉取项目
git clone https://github.com/wgy2006/wgy666.git
cd wgy666/backend

# 创建配置文件
cat > .env << 'ENVEOF'
GITHUB_TOKEN=ghp_你的token
GITHUB_WEBHOOK_SECRET=你的webhook_secret
LLM_API_KEY=你的llm_key
LLM_API_BASE_URL=https://models.sjtu.edu.cn/api/v1
LLM_MODEL=deepseek-reasoner
ENVEOF

# 安装依赖
uv sync

# 启动测试
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问 `http://服务器IP:8000/docs` 看到 Swagger 文档说明启动成功。

---

## 4. 配置 systemd 服务（关终端后保持运行）

```bash
sudo tee /etc/systemd/system/issuescope.service << 'SERVICEOF'
[Unit]
Description=IssueScope Backend
After=network.target

[Service]
Type=simple
User=你的用户名
WorkingDirectory=/home/你的用户名/wgy666/backend
ExecStart=/home/你的用户名/.local/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICEOF
```

**替换上述内容中的 `你的用户名` 为实际用户名：**

```bash
whoami  # 查看你的用户名
```

然后用 vim 或 nano 编辑：
```bash
sudo nano /etc/systemd/system/issuescope.service
```

替换完成后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now issuescope

# 查看状态
sudo systemctl status issuescope

# 查看日志
sudo journalctl -u issuescope -f
```

---

## 5. 防火墙设置

Azure 服务器需在 Portal 中添加入站规则放行 8000 端口：

1. 登录 Azure Portal
2. 进入虚拟机 → 网络设置 → 添加入站端口规则
3. 目标端口范围：`8000`
4. 协议：`TCP`
5. 优先级：`1000`

---

## 6. 配置 GitHub Webhook

进入目标 GitHub 仓库 → Settings → Webhooks → Add webhook：

| 字段 | 值 |
|------|-----|
| **Payload URL** | `http://服务器IP:8000/api/webhooks/github` |
| **Content type** | `application/json` |
| **Secret** | 与 `.env` 里的 `GITHUB_WEBHOOK_SECRET` 一致 |
| **SSL verification** | **Disable**（因为用 HTTP） |
| **Events** | 选 Issues，或 Let me select individual events |

---

## 7. 验证部署

```bash
# 测试健康检查
curl http://服务器IP:8000/api/health

# 测试 Webhook 接收
curl -X POST http://服务器IP:8000/api/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -d '{}'

# 测试仓库同步
curl -X POST http://服务器IP:8000/api/repositories/sync \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/fastapi/fastapi", "max_issues": 5}'
```

---

## 8. 后续扩展

### 8.1 PostgreSQL 数据库

```bash
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

### 8.2 Nginx 反代（如需 HTTPS）

```bash
sudo apt install -y nginx
```

配置 `/etc/nginx/sites-enabled/issuescope`：

```nginx
server {
    listen 80;
    server_name 你的域名;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 常用命令速查

```bash
# 重启服务
sudo systemctl restart issuescope

# 查看实时日志
sudo journalctl -u issuescope -f

# 更新代码后重启
cd ~/wgy666 && git pull && sudo systemctl restart issuescope

# 停止服务
sudo systemctl stop issuescope
```
