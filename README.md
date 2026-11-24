# 掌柜文书与日期智能体

本仓库包含两个相互独立的项目：

- `wenshu_project/`：基于 FastAPI、LangGraph、MySQL、Elasticsearch 和 Qdrant 的数据问答后端。
- `date-agent-frontend/`：基于 Vue 3 与 Vite 的前端。

## 后端启动

```powershell
cd wenshu_project
uv sync
uv run uvicorn main:app --reload --port 8000
```

后端配置位于 `wenshu_project/conf/app_config.yaml`。运行前通过环境变量提供敏感配置：

```powershell
$env:DB_META_PASSWORD = "你的元数据库密码"
$env:DB_DW_PASSWORD = "你的数据仓库密码"
$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
```

Docker 服务可通过以下命令启动：

```powershell
cd wenshu_project/docker
docker compose up -d
```

`bge-large-zh-v1.5` 的模型权重未提交到 Git，以免超过 GitHub 文件大小限制。首次启动前下载到指定目录：

```powershell
huggingface-cli download BAAI/bge-large-zh-v1.5 `
  --local-dir wenshu_project/docker/embedding/bge-large-zh-v1.5
```

MySQL 容器密码可通过 `MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD` 环境变量覆盖。

## 前端启动

```powershell
cd date-agent-frontend
npm install
npm run dev
```

开发服务器会将 `/api` 请求代理到 `http://localhost:8000`。
