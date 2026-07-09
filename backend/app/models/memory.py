"""长期记忆体系的 ORM 模型（画像 + 分级时效调研结论）。

schema 的权威来源是 init.sql（本仓库无 Alembic，init_db()/create_all 未启用），
这些声明与 init.sql 保持一致，复用 message.py 的同一个 declarative Base，使
Base.metadata 汇总全部表；读写层（service/memory/*.py）走原生 text() SQL，不依赖
这里的 ORM 查询接口。
"""
from sqlalchemy import (
    Column,
    Index,
    Integer,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.sql import func

from app.models.message import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(String(255), primary_key=True)
    risk_preference = Column(String(20))          # conservative/moderate/aggressive
    focus_tickers = Column(ARRAY(Text))           # 每项匹配 ^[A-Z]{1,5}$
    investment_style = Column(String(20))         # value/growth/income/quant
    notes = Column(JSONB)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now())


class ConclusionMemory(Base):
    __tablename__ = "conclusion_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False)
    fact_type = Column(String(20), nullable=False)       # fundamentals/filing/news
    fact_text = Column(Text, nullable=False)
    metric_name = Column(String(64), nullable=False)     # 规范化 concept slug，非空
    source = Column(String(50), nullable=False)
    extracted_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    expires_at = Column(TIMESTAMP, nullable=False)        # 由代码按 fact_type 计算

    __table_args__ = (
        UniqueConstraint("ticker", "fact_type", "metric_name", name="conclusion_memory_ticker_fact_type_metric_name_key"),
        Index("idx_conclusion_memory_ticker", "ticker"),
    )
