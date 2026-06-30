from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from router import chat_rt, history_rt

app = FastAPI(title="Invest+ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # 不启用 allow_credentials：项目无 cookie 鉴权，且 allow_origins=["*"] 与
    # allow_credentials=True 在 CORS 规范下不能共存（带凭据请求会被浏览器拒绝）。
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_rt.router)
app.include_router(history_rt.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
