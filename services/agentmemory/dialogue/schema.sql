-- ============================================================
-- dialogue_library · 对话库（情景记忆子集）Schema v1.0.0
-- 位置: E:\CorpusPipeline\dialogue_library\data\dialogue.db
-- 对齐约定:
--   * dialog_mode 双轨（协作 / 教练） -> sessions.kind / turns.mode
--   * agentmemory 字段风格           -> sessionId / timestamp(ISO8601 UTC) / channel
--   * GFCC 契约信号引用               -> turns.signal_ref
-- 检索: SQLite FTS5 trigram（中文短语可查）
-- ============================================================

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    kind         TEXT NOT NULL DEFAULT 'collab',   -- collab=协作 / coach=教练（对应 dialog_mode 双轨）
    title        TEXT,
    participants TEXT,                              -- 参与成员，如 "windows,mac,ai"
    created_at   TEXT NOT NULL,                     -- ISO8601 UTC
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,                    -- 会话内轮次序号
    role       TEXT NOT NULL,                       -- user / assistant / ai / system
    content    TEXT NOT NULL,
    mode       TEXT,                                -- 双轨对话模式（协作 / 教练）
    signal_ref TEXT,                                -- 关联 GFCC 契约信号，如 THOMAS:5211:v1.0.0
    channel    TEXT NOT NULL DEFAULT 'manual',      -- gfcc / demopeter / agentmemory / manual
    ts         TEXT NOT NULL,                       -- ISO8601 UTC
    UNIQUE (session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);

-- 中文友好的全文检索（trigram tokenizer）
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    content, role, mode, signal_ref,
    tokenize = 'trigram',
    content = 'turns',
    content_rowid = 'id'
);

CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
    INSERT INTO turns_fts(rowid, content, role, mode, signal_ref)
    VALUES (new.id, new.content, new.role, new.mode, new.signal_ref);
END;

CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
    INSERT INTO turns_fts(turns_fts, rowid, content, role, mode, signal_ref)
    VALUES ('delete', old.id, old.content, old.role, old.mode, old.signal_ref);
END;

CREATE TRIGGER IF NOT EXISTS turns_au AFTER UPDATE ON turns BEGIN
    INSERT INTO turns_fts(turns_fts, rowid, content, role, mode, signal_ref)
    VALUES ('delete', old.id, old.content, old.role, old.mode, old.signal_ref);
    INSERT INTO turns_fts(rowid, content, role, mode, signal_ref)
    VALUES (new.id, new.content, new.role, new.mode, new.signal_ref);
END;
