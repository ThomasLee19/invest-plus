import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from router import chat_rt, history_rt

app = FastAPI(title="Invest+ API")

# 本项目是刻意的单用户、无鉴权 demo（见 chat_rt.py 的硬编码 USER_ID="1"）。
# 即便如此也不留 allow_origins=["*"] 的静默通配：CORS 源从 FRONTEND_ORIGIN 环境
# 变量读取，缺省回退到本地 Vite dev server（vite.config.ts 里 server.port=5181）。
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5181")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    # 不启用 allow_credentials：项目无 cookie 鉴权。
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_rt.router)
app.include_router(history_rt.router)


@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
