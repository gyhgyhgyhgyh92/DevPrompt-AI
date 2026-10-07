"""SQLite DDL（L1 会话存储，F-501）。幂等；SQL 集中于 memory/（MUST-06）。"""

SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS forge_sessions (
  session_id TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  state      TEXT NOT NULL,
  version    INTEGER NOT NULL DEFAULT 0,
  payload    TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON forge_sessions (user_id);
"""
