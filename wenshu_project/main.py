from Lib import uuid
from fastapi import FastAPI, Request

from app.api.routers.query_router import query_router
from app.api.schemas.query_schema import QuerySchema
from app.core.context import request_id_ctx_var
from app.core.logs.lifespan import lifespan

# 创建fastapi 实例
app = FastAPI(lifespan=lifespan)

# 添加路由
app.include_router(query_router)
# 定义中间键
@app.middleware("http")
async def add_request_context_var(request: Request, call_next):
    # 赋值上下文变量--用户ID
    request_id_ctx_var.set(uuid.uuid4())
    # 请求目标
    response = await call_next(request)

    return response