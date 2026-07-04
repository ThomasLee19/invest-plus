from sqlalchemy import Column, Index, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String(16), primary_key=True)
    session_name = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    message_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    session_id = Column(String(16), nullable=False)
    user_question = Column(Text, nullable=False)
    model_answer = Column(Text, nullable=False)
    think = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # 热查询是 WHERE session_id = ? ORDER BY created_at，复合索引同时命中过滤与排序。
    __table_args__ = (
        Index("idx_messages_session_id_created_at", "session_id", "created_at"),
    )
