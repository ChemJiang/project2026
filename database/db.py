"""Unified database connection management: all code obtains connections through get_connection()."""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "mes.db"


def now_str() -> str:
    """Unified timestamp format YYYY-MM-DD HH:MM:SS, matching SQLite datetime('now','localtime')."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
