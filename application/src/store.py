"""Append-only capture store: SQLite for capture rows, files for raw bodies.

The captures table is the chain of custody. Rows are only ever inserted.
Raw bodies are deduped by sha256 but every (source, fetched_at, hash) row is kept.

Migrations are additive only (new tables, new nullable columns) and recorded in
MIGRATIONS with a version number. Nothing here ever rewrites or deletes a row.
"""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# TSA_DATA_DIR lets tests (and odd deployments) point the store somewhere else.
DATA_DIR = Path(os.environ.get("TSA_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "archive.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,          -- UTC ISO 8601
    url TEXT NOT NULL,
    http_status INTEGER,               -- NULL if request failed outright
    content_hash TEXT,                 -- sha256 hex of raw body; NULL on failure
    error TEXT                         -- request exception text, if any
);
CREATE INDEX IF NOT EXISTS idx_captures_source_time
    ON captures (source_id, fetched_at);
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    note TEXT
);
"""

# (version, note, [statements]). Each statement must be safe to skip if already applied.
MIGRATIONS = [
    (
        1,
        "parsed_rows, parse_errors, captures.is_mock, captures.content_type",
        [
            """CREATE TABLE IF NOT EXISTS parsed_rows (
                id INTEGER PRIMARY KEY,
                capture_id INTEGER NOT NULL REFERENCES captures(id),
                source_id TEXT NOT NULL,
                terminal TEXT,
                kind TEXT NOT NULL,          -- gate_day | empty_rule | notice | slot_window | turn_time | erd | table_row
                entity_key TEXT NOT NULL,    -- e.g. 'T18|gate|2026-09-25' or 'WUT|empty|HLC|40HC|drop'
                row_json TEXT NOT NULL,      -- canonical JSON, sorted keys
                row_hash TEXT NOT NULL       -- sha256 of row_json
            )""",
            "CREATE INDEX IF NOT EXISTS idx_parsed_entity ON parsed_rows(source_id, entity_key, capture_id)",
            "CREATE INDEX IF NOT EXISTS idx_parsed_capture ON parsed_rows(capture_id)",
            "CREATE INDEX IF NOT EXISTS idx_parsed_terminal_kind ON parsed_rows(terminal, kind)",
            """CREATE TABLE IF NOT EXISTS parse_errors (
                id INTEGER PRIMARY KEY,
                capture_id INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                error TEXT NOT NULL,
                at TEXT NOT NULL
            )""",
            "ALTER TABLE captures ADD COLUMN is_mock INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE captures ADD COLUMN content_type TEXT",
        ],
    ),
]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _migrate(conn: sqlite3.Connection) -> None:
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    for version, note, statements in MIGRATIONS:
        if version in applied:
            continue
        for stmt in statements:
            if stmt.startswith("ALTER TABLE"):
                # "ALTER TABLE <t> ADD COLUMN <c> ..."
                parts = stmt.split()
                table, column = parts[2], parts[5]
                if _column_exists(conn, table, column):
                    continue
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at, note) VALUES (?, ?, ?)",
            (version, datetime.now(timezone.utc).isoformat(timespec="seconds"), note),
        )
    conn.commit()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def raw_path(content_hash: str, ext: str = "html") -> Path:
    return RAW_DIR / content_hash[:2] / f"{content_hash}.{ext}"


def find_raw(content_hash: str) -> Path | None:
    shard = RAW_DIR / content_hash[:2]
    if not shard.exists():
        return None
    for p in shard.iterdir():
        if p.stem == content_hash:
            return p
    return None


def store_raw(body: bytes, ext: str = "html") -> str:
    """Write raw body to content-addressed storage. Returns sha256 hex."""
    digest = hashlib.sha256(body).hexdigest()
    path = raw_path(digest, ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(body)
    return digest


def record_capture(
    conn: sqlite3.Connection,
    source_id: str,
    url: str,
    http_status: int | None,
    content_hash: str | None,
    error: str | None = None,
    is_mock: bool = False,
    content_type: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO captures (source_id, fetched_at, url, http_status, content_hash, error, is_mock, content_type)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_id,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            url,
            http_status,
            content_hash,
            error,
            1 if is_mock else 0,
            content_type,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)
