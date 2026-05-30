import sqlite3
from datetime import datetime
from config import DATABASE_PATH


class EmotionMemory:
    def __init__(self, db_path=None):
        self.db_path = db_path or DATABASE_PATH
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS logs 
                            (time TEXT, user_input TEXT, emotion TEXT, score INTEGER)''')

    def save_log(self, text, emotion):
        # 将情绪转化为分数（建模思路：正面+1，负面-1）
        score = 1 if emotion == "happy" else -1
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO logs VALUES (?, ?, ?, ?)",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text, emotion, score))

    def get_recent_trend(self):
        """获取最近 5 次的情绪趋势"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT score FROM logs ORDER BY time DESC LIMIT 5")
            scores = [row[0] for row in cursor.fetchall()]
            return sum(scores)  # 负数表示近期心情低落