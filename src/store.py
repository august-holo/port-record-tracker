"""Append-only capture store: SQLite for capture rows, files for raw bodies.

The captures table is the chain of custody. Rows are only ever inserted.
Raw bodies are deduped by sha256 but every (source, fetched_at, hash) row is kept.
"""
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
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
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def store_raw(body: bytes) -> str:
    """Write raw body to content-addressed storage. Returns sha256 hex."""
    digest = hashlib.sha256(body).hexdigest()
    shard = RAW_DIR / digest[:2]
    shard.mkdir(exist_ok=True)
    path = shard / f"{digest}.html"
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
) -> None:
    conn.execute(
        "INSERT INTO captures (source_id, fetched_at, url, http_status, content_hash, error)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            source_id,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            url,
            http_status,
            content_hash,
            error,
        ),
    )
    conn.commit()
