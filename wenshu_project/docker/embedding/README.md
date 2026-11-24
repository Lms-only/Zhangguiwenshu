# 向量模型

本项目使用 `BAAI/bge-large-zh-v1.5`。模型权重体积较大，不提交到 Git 仓库。

首次启动前，在本仓库根目录执行：

```powershell
huggingface-cli download BAAI/bge-large-zh-v1.5 `
  --local-dir wenshu_project/docker/embedding/bge-large-zh-v1.5
```

下载完成后，`docker-compose.yaml` 会将模型目录挂载到 embedding 容器中。
