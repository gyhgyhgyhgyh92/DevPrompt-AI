"""SQLite DDL（L1 会话存储 F-501 + L3 偏好存储 F-503）。幂等；SQL 集中于 memory/（MUST-06）。"""

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

# F-503 L3 双表：偏好向量（user_id 分区间，四维 REAL）+ 采纳历史（审查中等 10 补历史表）。
PREFERENCE_DDL = """
CREATE TABLE IF NOT EXISTS preference_vectors (
  user_id        TEXT PRIMARY KEY,
  detail_level   REAL NOT NULL DEFAULT 0.5,
  include_diff   REAL NOT NULL DEFAULT 0.5,
  specify_tests  REAL NOT NULL DEFAULT 0.5,
  max_files_norm REAL NOT NULL DEFAULT 0.5,
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS adoption_history (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id           TEXT NOT NULL,
  session_id        TEXT NOT NULL,
  variant           TEXT NOT NULL,
  edited            INTEGER NOT NULL DEFAULT 0,
  edited_text_ratio REAL NOT NULL DEFAULT 0,
  features_json     TEXT NOT NULL,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_adoption_history_user ON adoption_history (user_id);
"""
