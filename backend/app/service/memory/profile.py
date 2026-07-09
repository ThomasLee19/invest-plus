"""跨会话用户画像记忆的读写层。

原生 text() SQL（与 chat_rt.py 同风格，便于 mock 断言），自开独立 SessionLocal。
字段更新语义（v7，与逐字稿"更新覆盖"的一处刻意偏离，已在计划中记录）：
  - risk_preference / investment_style：标量枚举，最新值生效（整体覆盖）。用
    COALESCE(EXCLUDED, 旧值) 实现"有新值就覆盖、本次没抽到则保留旧值"，避免某次
    抽取未提及该字段时把历史偏好静默清空。
  - focus_tickers：数组，合并追加（并集去重），不整体替换——本次没提到的历史关注
    标的不丢失，契合"长期记住用户关注什么"的核心卖点。
两种字段两套策略，不可混用。
"""
import json

from sqlalchemy import text

# bare import (与 chat_rt.py 同一模块名 utils.database)，共用同一个 engine/连接池，
# 而非以 app.utils.database 再建一份重复的 engine。
from utils.database import SessionLocal


def recall_user_profile(user_id: str) -> dict | None:
    """查询单条用户画像；不存在返回 None。每次 /chat 由 chat_rt.py 用独立 session 调一次。"""
    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT user_id, risk_preference, focus_tickers, investment_style, notes "
                "FROM user_profiles WHERE user_id = :uid"
            ),
            {"uid": user_id},
        ).fetchone()
    if row is None:
        return None
    return {
        "user_id": row.user_id,
        "risk_preference": row.risk_preference,
        "focus_tickers": list(row.focus_tickers) if row.focus_tickers else [],
        "investment_style": row.investment_style,
        "notes": row.notes,
    }


def upsert_user_profile(
    user_id: str,
    risk_preference: str | None = None,
    focus_tickers: list[str] | None = None,
    investment_style: str | None = None,
    notes: dict | str | None = None,
) -> None:
    """插入或更新画像。标量字段最新值生效（COALESCE 保留旧值防止 None 清空），
    focus_tickers 并集去重合并。CAST(... AS ...) 而非 ::（避免 SQLAlchemy 把 :: 后的
    标识符误当作绑定参数）；'{}' 空数组 CAST 使 EXCLUDED/旧值任一为 NULL 时并集不塌成 NULL。"""
    notes_json = json.dumps(notes, ensure_ascii=False) if notes is not None else None
    with SessionLocal() as db:
        try:
            db.execute(
                text(
                    """
                    INSERT INTO user_profiles
                        (user_id, risk_preference, focus_tickers, investment_style, notes)
                    VALUES (:uid, :risk, :focus, :style, CAST(:notes AS jsonb))
                    ON CONFLICT (user_id) DO UPDATE SET
                        risk_preference = COALESCE(EXCLUDED.risk_preference, user_profiles.risk_preference),
                        investment_style = COALESCE(EXCLUDED.investment_style, user_profiles.investment_style),
                        focus_tickers = ARRAY(SELECT DISTINCT unnest(
                            COALESCE(user_profiles.focus_tickers, CAST('{}' AS text[]))
                            || COALESCE(EXCLUDED.focus_tickers, CAST('{}' AS text[]))
                        )),
                        notes = COALESCE(EXCLUDED.notes, user_profiles.notes),
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "uid": user_id,
                    "risk": risk_preference,
                    "focus": focus_tickers,
                    "style": investment_style,
                    "notes": notes_json,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
