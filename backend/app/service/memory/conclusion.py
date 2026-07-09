"""分级时效调研结论记忆的读写层。

原生 text() SQL，自开独立 SessionLocal。expires_at 由 _compute_expires_at 确定性
计算后写入（NOT NULL），不接受 LLM 输出的时效字段。召回一律 WHERE expires_at > now()
过滤过期记录（不再需要 ttl_class 二次查表）。
"""
from datetime import datetime, timedelta

from sqlalchemy import text

# bare import (与 chat_rt.py 同一模块名 utils.database)，共用同一个 engine/连接池。
from utils.database import SessionLocal

# fundamentals/filing 视为较稳定 → 90 天；news 时效短 → 30 天。
_TTL_DAYS = {"fundamentals": 90, "filing": 90, "news": 30}


def _compute_expires_at(fact_type: str, extracted_at: datetime) -> datetime:
    """按 fact_type 确定性计算过期时间。fact_type 已由 schema 校验限定为三个枚举值
    之一（上游 _validate_extracted_fields 保证），故此处直接字典取值、无默认分支——
    未知值会以 KeyError 就地暴露抽取输出漂移，而非静默兜底一个错误的时效。"""
    return extracted_at + timedelta(days=_TTL_DAYS[fact_type])


def recall_conclusion_facts(ticker: str, fact_types: list[str] | None = None) -> list[dict]:
    """召回某 ticker 未过期的调研结论；fact_types 为 None 时不限类型。
    WHERE expires_at > now() 用数据库时钟判定过期，避免应用/DB 时钟漂移带来的边界抖动。"""
    sql = (
        "SELECT ticker, fact_type, fact_text, metric_name, source, extracted_at, expires_at "
        "FROM conclusion_memory WHERE ticker = :ticker AND expires_at > now()"
    )
    params: dict = {"ticker": ticker}
    if fact_types:
        sql += " AND fact_type = ANY(:fact_types)"
        params["fact_types"] = fact_types
    with SessionLocal() as db:
        rows = db.execute(text(sql), params).fetchall()
    return [
        {
            "ticker": r.ticker,
            "fact_type": r.fact_type,
            "fact_text": r.fact_text,
            "metric_name": r.metric_name,
            "source": r.source,
            "extracted_at": r.extracted_at,
            "expires_at": r.expires_at,
        }
        for r in rows
    ]


def upsert_conclusion_fact(
    ticker: str,
    fact_type: str,
    fact_text: str,
    metric_name: str,
    source: str,
    extracted_at: datetime | None = None,
) -> None:
    """按语义键 (ticker, fact_type, metric_name) 幂等 upsert。重复抽取同一语义键只更新
    内容/时间戳，不新增行。expires_at 由 _compute_expires_at 计算，绝不接受外部时效值。"""
    extracted_at = extracted_at or datetime.now()
    expires_at = _compute_expires_at(fact_type, extracted_at)
    with SessionLocal() as db:
        try:
            db.execute(
                text(
                    """
                    INSERT INTO conclusion_memory
                        (ticker, fact_type, fact_text, metric_name, source, extracted_at, expires_at)
                    VALUES (:ticker, :fact_type, :fact_text, :metric_name, :source, :extracted_at, :expires_at)
                    ON CONFLICT (ticker, fact_type, metric_name) DO UPDATE SET
                        fact_text = EXCLUDED.fact_text,
                        extracted_at = EXCLUDED.extracted_at,
                        expires_at = EXCLUDED.expires_at
                    """
                ),
                {
                    "ticker": ticker,
                    "fact_type": fact_type,
                    "fact_text": fact_text,
                    "metric_name": metric_name,
                    "source": source,
                    "extracted_at": extracted_at,
                    "expires_at": expires_at,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
