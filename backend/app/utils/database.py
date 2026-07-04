from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.message import Base
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Set it in your .env file (see .env.example)."
    )

# pool_pre_ping：每次借出连接前先探活，避免 Postgres 容器空闲/重启后返回已失效
# 的死连接；pool_recycle：超过 30 分钟的连接主动回收，防止被服务端静默断开。
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
