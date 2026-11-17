"""可观测性模块 DDL（SQL 集中 memory/，MUST-06；2026-11-12）。"""

from __future__ import annotations

TRACE_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS trace_events (
  trace_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  turn_id TEXT NOT NULL,
  turn_index INTEGER NOT NULL,
  run_id TEXT NOT NULL DEFAULT '',
  parent_id TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL DEFAULT '',
  duration_ms INTEGER NOT NULL DEFAULT 0,
  input_json TEXT NOT NULL DEFAULT '{}',
  output_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}',
  attributes_json TEXT NOT NULL DEFAULT '{}',
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (trace_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_trace_session ON trace_events (session_id, turn_index, seq);
CREATE INDEX IF NOT EXISTS idx_trace_kind ON trace_events (session_id, kind, started_at);
CREATE INDEX IF NOT EXISTS idx_trace_event ON trace_events (event_id);
CREATE INDEX IF NOT EXISTS idx_trace_started ON trace_events (started_at);
"""

METRICS_ALERTS_DDL = """
CREATE TABLE IF NOT EXISTS metrics_alerts (
  alert_id TEXT PRIMARY KEY,
  rule_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  scope_kind TEXT NOT NULL,
  scope_key TEXT NOT NULL,
  metric TEXT NOT NULL,
  observed REAL NOT NULL,
  threshold REAL NOT NULL,
  message TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  resolved_at TEXT NOT NULL DEFAULT '',
  cooldown_until TEXT NOT NULL DEFAULT '',
  schema_version INTEGER NOT NULL
);
DROP INDEX IF EXISTS idx_alert_active;
DELETE FROM metrics_alerts WHERE status='active' AND rowid NOT IN (
  SELECT MIN(rowid) FROM metrics_alerts WHERE status='active'
  GROUP BY rule_id, scope_kind, scope_key
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_active
  ON metrics_alerts (rule_id, scope_kind, scope_key) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_alert_status ON metrics_alerts (status, last_seen_at);
"""
"""D-03 迁移（2026-11-14）：唯一约束只作用于 active 行。

旧索引把 status 也纳入唯一键，同一 scope 第二次 resolved 时会与历史 resolved
行冲突（MT-08 复现）。先清理历史竞态可能留下的重复 active 行，再用 partial
index 把约束收窄到 active；resolved 历史可保留多行。
"""

REPLAY_DDL = """
CREATE TABLE IF NOT EXISTS replay_runs (
  run_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  left_trace_id TEXT NOT NULL,
  right_trace_id TEXT NOT NULL DEFAULT '',
  matched_nodes INTEGER NOT NULL DEFAULT 0,
  mismatched_nodes INTEGER NOT NULL DEFAULT 0,
  missing_nodes INTEGER NOT NULL DEFAULT 0,
  result_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  ended_at TEXT NOT NULL DEFAULT '',
  schema_version INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replay_created ON replay_runs (created_at);

CREATE TABLE IF NOT EXISTS replay_nodes (
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  match INTEGER NOT NULL,
  expected_json TEXT NOT NULL DEFAULT '{}',
  actual_json TEXT NOT NULL DEFAULT '{}',
  diff_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (run_id, seq)
);
"""
