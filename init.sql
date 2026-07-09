
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- 创建 users 表
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 创建时间
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP  -- 更新时间
);

-- 创建会话表
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(16) PRIMARY KEY,
    session_name VARCHAR(255) NOT NULL,  
    user_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 创建时间
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP  -- 更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at  ON sessions(created_at);

-- 创建 messages 表
CREATE TABLE IF NOT EXISTS messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(16) NOT NULL,
    user_question TEXT NOT NULL,
    model_answer TEXT NOT NULL,
    documents  TEXT,  -- 存储序列化后的 JSON 字符串（列类型为 TEXT，非 jsonb）
    recommended_questions TEXT,  
    think TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 创建时间
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP  -- 更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
-- 复合索引：messages 的热查询是 WHERE session_id = ? ORDER BY created_at，
-- (session_id, created_at) 复合索引可同时命中过滤和排序，避免额外排序；
-- 该复合索引的最左前缀已覆盖单独按 session_id 查询的场景，因此不再单独建
-- idx_messages_session_id。
CREATE INDEX IF NOT EXISTS idx_messages_session_id_created_at ON messages(session_id, created_at);

-- 创建知识库表
CREATE TABLE IF NOT EXISTS knowledgebases (
    id SERIAL PRIMARY KEY,  -- 主键，自增
    user_id VARCHAR(255) NOT NULL,       -- 用户 ID
    file_name VARCHAR(255) NOT NULL,     -- 文件名称
    session_id VARCHAR(16),              -- 会话 ID（NULL 表示数据集全局上传）
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 创建时间
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP  -- 更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_knowledgebases_user_id ON knowledgebases(user_id);
CREATE INDEX IF NOT EXISTS idx_knowledgebases_created_at ON knowledgebases(created_at);
CREATE INDEX IF NOT EXISTS idx_knowledgebases_session_id ON knowledgebases(session_id);

-- 跨会话用户画像记忆表（单用户 demo：user_id 即主键，无多租户）
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id VARCHAR(255) PRIMARY KEY,
    risk_preference VARCHAR(20),          -- 枚举: conservative/moderate/aggressive
    focus_tickers TEXT[],                 -- 每项匹配 ^[A-Z]{1,5}$
    investment_style VARCHAR(20),         -- 枚举: value/growth/income/quant
    notes JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 分级时效调研结论记忆表。UNIQUE(ticker, fact_type, metric_name) 是幂等 upsert 的
-- 语义键；metric_name 强制非空（定性事实也须有规范化 concept slug），从根源消除去重失效。
-- expires_at 由代码按 fact_type 确定性计算后写入（NOT NULL），不由 LLM 输出。
CREATE TABLE IF NOT EXISTS conclusion_memory (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    fact_type VARCHAR(20) NOT NULL,       -- fundamentals/filing/news（quote 永不入库）
    fact_text TEXT NOT NULL,
    metric_name VARCHAR(64) NOT NULL,     -- 规范化 concept slug，定量定性事实都必须有，不允许 NULL/空串
    source VARCHAR(50) NOT NULL,
    extracted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,        -- 写入时由代码按 fact_type 确定性计算，不由 LLM 输出
    UNIQUE (ticker, fact_type, metric_name)
);
CREATE INDEX IF NOT EXISTS idx_conclusion_memory_ticker ON conclusion_memory(ticker);