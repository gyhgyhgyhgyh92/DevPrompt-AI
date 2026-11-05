"""SQLite DDL（会话 / 多轮 turn / 项目记忆 / 设置 / 隔离区 / 模型目录）。

幂等；SQL 集中于 memory/（MUST-06）。
"""

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

# 多轮 turn（2026-10-20）：append-only，一次 optimize 一行，状态机作用域下沉到 turn。
# (session_id, turn_index) 唯一索引 = 乐观锁：重复提交在 DB 层被拒（MUST-15，不靠前端防抖）。
# output_json 存方案全文，summary_json 存机器摘要——装配上下文只读摘要，正文按需懒加载，
# 避免「全量 payload 覆盖」随轮数线性写放大。
TURNS_DDL = """
CREATE TABLE IF NOT EXISTS forge_turns (
  turn_id             TEXT PRIMARY KEY,
  session_id          TEXT NOT NULL,
  turn_index          INTEGER NOT NULL,
  state               TEXT NOT NULL,
  input               TEXT NOT NULL,
  facts_json          TEXT NOT NULL DEFAULT '[]',
  clarifications_json TEXT NOT NULL DEFAULT '{}',
  output_json         TEXT NOT NULL DEFAULT '[]',
  summary_json        TEXT NOT NULL DEFAULT '{}',
  usage_json          TEXT NOT NULL DEFAULT '{}',
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_session_index ON forge_turns (session_id, turn_index);
"""

# 启动自愈（2026-11-04）：把崩溃遗留的未完成 turn 收尾。
# 只处理「超过阈值仍停在活跃态」的行——运行中的 turn 不能被误杀；
# AGENTIC 是星型拓扑的决策态，进程崩溃时会停在它上面（不含 ASKING/CONFIRMING，
# 那两态是等用户，不是执行中）。
ORPHAN_TURNS_SQL = """
UPDATE forge_turns
   SET state = 'ABORTED'
 WHERE state IN ('INIT', 'AGENTIC')
   AND created_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)
"""

#: 对应会话一并收尾：版本号自增，避免下一次 CAS 撞上旧 version。
ORPHAN_SESSIONS_SQL = """
UPDATE forge_sessions
   SET state = 'ABORTED',
       version = version + 1,
       updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
 WHERE state IN ('INIT', 'AGENTIC', 'RETRIEVING', 'PROBING', 'GENERATING', 'RANKING')
   AND session_id IN (
     SELECT session_id FROM forge_turns
      WHERE state = 'ABORTED'
        AND created_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)
   )
"""


# L2 项目记忆（2026-10-20）：结构化真源，替代 git notes 的自由文本 blob。
# 检索式注入：score = confidence × 90 天半衰期 × key 匹配度；命中回写 hit_count/last_hit_at
# （判断记忆是否真的被用到的唯一客观信号）。superseded_by 指向覆盖它的新 key，不物理删除。
PROJECT_NOTES_DDL = """
CREATE TABLE IF NOT EXISTS project_notes (
  project_root  TEXT NOT NULL,
  kind          TEXT NOT NULL,
  key           TEXT NOT NULL,
  value         TEXT NOT NULL,
  evidence      TEXT NOT NULL DEFAULT '',
  confidence    REAL NOT NULL DEFAULT 0.5,
  hit_count     INTEGER NOT NULL DEFAULT 0,
  last_hit_at   TEXT,
  superseded_by TEXT,
  source        TEXT NOT NULL DEFAULT 'auto',
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (project_root, kind, key)
);
CREATE INDEX IF NOT EXISTS idx_notes_project ON project_notes (project_root);
"""
# F-604 设置持久化（T6-11）：流程参数键值表。模型服务密钥在 settings.json 文件（0600），
# 不入库（MUST-19 修订后语义：密钥不入库、不进日志）。
SETTINGS_DDL = """
CREATE TABLE IF NOT EXISTS app_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

# N-1 启动自愈隔离区：integrity_check 判定损坏的行**移入此表而非直接删除**。
# 保留原始行内容供人工取证（本地单用户工具，误删不可恢复）；row_json 可能含用户原句，
# 因此**禁止**把该表内容写入日志或 /health 响应（MUST-19）。
QUARANTINE_DDL = """
CREATE TABLE IF NOT EXISTS forge_quarantine (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  table_name TEXT NOT NULL,
  row_json   TEXT NOT NULL,
  reason     TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

# 模型目录缓存（2026-10-17 动态模型目录）：按 (provider_key, base_url) 缓存最近一次
# 拉取结果。**不含任何密钥列**——api_key 只在内存中用于本次请求（MUST-19）。
# payload_json 存合并后的条目列表（含 source 标注），拉取失败时读它兜底，保证
# 「刷新失败不清空已配模型」。
MODEL_CATALOG_DDL = """
CREATE TABLE IF NOT EXISTS model_catalog (
  provider_key TEXT NOT NULL,
  base_url     TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  fetched_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (provider_key, base_url)
);
"""
