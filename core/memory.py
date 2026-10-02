import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from typing import Iterator
from config import DATABASE_PATH

SCHEMA_VERSION = 1


class SchemaVersionError(sqlite3.DatabaseError):
    """Opening a newer database with older product code would risk its records."""


def validate_schema_version(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
        raise SchemaVersionError("Database schema is newer; upgrade the application before opening it")


@contextmanager
def database_connection(db_path: str) -> Iterator[sqlite3.Connection]:
    """Commit or roll back each operation, then always release its connection."""
    with closing(sqlite3.connect(db_path, timeout=5.0)) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        with conn:
            yield conn


class EmotionMemory:
    def __init__(self, db_path=None):
        self.db_path = db_path or DATABASE_PATH
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with database_connection(self.db_path) as conn:
            validate_schema_version(conn)
            conn.execute('''CREATE TABLE IF NOT EXISTS logs 
                            (time TEXT, user_input TEXT, emotion TEXT, score INTEGER)''')

    def save_log(self, text, emotion):
        # 将情绪转化为分数（建模思路：正面+1，负面-1）
        score = 1 if emotion == "happy" else -1
        with database_connection(self.db_path) as conn:
            validate_schema_version(conn)
            conn.execute("INSERT INTO logs VALUES (?, ?, ?, ?)",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text, emotion, score))

    def get_recent_trend(self):
        """获取最近 5 次的情绪趋势"""
        with database_connection(self.db_path) as conn:
            validate_schema_version(conn)
            cursor = conn.execute("SELECT score FROM logs ORDER BY time DESC LIMIT 5")
            scores = [row[0] for row in cursor.fetchall()]
            return sum(scores)  # 负数表示近期心情低落
