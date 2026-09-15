# SoulCompanion_AI/reports/report_generator.py
import os
import sqlite3
import sys
from datetime import datetime

# 确保能从项目根目录导入 config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import DATABASE_PATH

# 情绪归类（新旧两套表共用同一套词表）
POSITIVE_EMOTIONS = {"happy", "calm", "surprised"}
NEGATIVE_EMOTIONS = {"sad", "anxious", "angry", "fearful", "distressed"}


class ReportGenerator:
    def __init__(self, db_path=None):
        self.db_path = db_path or DATABASE_PATH
        # 确保输出目录存在
        os.makedirs("reports/output", exist_ok=True)

    @staticmethod
    def _has_table(conn, name: str) -> bool:
        """判断表是否存在（避免直接查询不存在的表而抛异常）。"""
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def _load_day(self, today: str):
        """
        读取当日交互记录，统一成 (时间, 孩子说了什么, 情绪, 分值) 四元组。

        优先读取新情绪管线的 emotion_records 表；若该表不存在或当天没有数据，
        再回退到旧版 logs 表（由 core/memory.py 写入），保证两条数据链路都能出报告。
        """
        with sqlite3.connect(self.db_path) as conn:
            if self._has_table(conn, "emotion_records"):
                rows = conn.execute(
                    """SELECT timestamp, source_text, category, valence
                       FROM emotion_records
                       WHERE timestamp LIKE ?
                       ORDER BY timestamp""",
                    (f"{today}%",),
                ).fetchall()
                if rows:
                    return [
                        (ts, text or "", cat or "neutral", val if val is not None else 0.0)
                        for ts, text, cat, val in rows
                    ]

            if self._has_table(conn, "logs"):
                return conn.execute(
                    "SELECT time, user_input, emotion, score FROM logs WHERE time LIKE ?",
                    (f"{today}%",),
                ).fetchall()

        return []

    def generate_daily_report(self):
        """读取 SQLite 数据库，生成今日儿童情感状态报告"""
        today = datetime.now().strftime("%Y-%m-%d")

        if not os.path.exists(self.db_path):
            print("❌ 数据库未找到，请先让小予和孩子聊聊天哦！")
            return

        try:
            records = self._load_day(today)
        except sqlite3.Error as e:
            print(f"❌ 读取数据库失败: {e}")
            return

        if not records:
            print("📝 今天还没有交互记录呢。")
            return

        # 数据分析
        total_interactions = len(records)
        positive_count = sum(1 for r in records if r[2] in POSITIVE_EMOTIONS)
        negative_count = sum(1 for r in records if r[2] in NEGATIVE_EMOTIONS)

        # 简单的健康度计算
        health_score = 100 - (negative_count * 15) + (positive_count * 5)
        health_score = max(0, min(100, health_score))  # 限制在 0-100 之间

        # 提取负面瞬间提醒家长（时间取 HH:MM，兼容 "YYYY-MM-DD HH:MM:SS" 与 ISO 格式）
        sad_moments = [
            f"[{str(r[0])[11:16]}] 孩子说: '{r[1]}'"
            for r in records
            if r[2] in NEGATIVE_EMOTIONS
        ]

        # 生成 Markdown 格式报告
        report_content = f"""# 🌟 小予机器人 - 每日儿童情感陪伴报告
**日期：** {today}
---
### 📊 交互概览
* **今日互动总次数：** {total_interactions} 次
* **开心时刻：** {positive_count} 次
* **低落时刻：** {negative_count} 次
* **💚 今日情绪健康指数：** {health_score} / 100

### 💡 小予的特别提醒
"""
        if sad_moments:
            report_content += "今天孩子有几次情绪低落的时刻，建议您下班后多陪陪孩子哦：\n"
            for moment in sad_moments:
                report_content += f"* {moment}\n"
        else:
            report_content += "今天宝宝的心情非常阳光！请继续保持哦。\n"

        # 写入文件
        report_filename = f"reports/output/Daily_Report_{today}.md"
        with open(report_filename, "w", encoding="utf-8") as f:
            f.write(report_content)

        print(f"\n✅ 报告已生成！请查看: {report_filename}")


# 如果单独运行此脚本，则直接生成报告
if __name__ == "__main__":
    generator = ReportGenerator()
    generator.generate_daily_report()
