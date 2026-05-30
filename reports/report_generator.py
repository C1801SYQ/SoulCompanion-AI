# SoulCompanion_AI/reports/report_generator.py
import sqlite3
import os
from datetime import datetime


class ReportGenerator:
    def __init__(self, db_path='data/emotional_db.sqlite'):
        self.db_path = db_path
        # 确保输出目录存在
        os.makedirs("reports/output", exist_ok=True)

    def generate_daily_report(self):
        """读取 SQLite 数据库，生成今日儿童情感状态报告"""
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            with sqlite3.connect(self.db_path) as conn:
                # 获取今天的对话记录
                cursor = conn.execute("SELECT time, user_input, emotion, score FROM logs WHERE time LIKE ?", (f"{today}%",))
                records = cursor.fetchall()
        except sqlite3.OperationalError:
            print("❌ 数据库未找到，请先让小予和孩子聊聊天哦！")
            return

        if not records:
            print("📝 今天还没有交互记录呢。")
            return

        # 数据分析
        total_interactions = len(records)
        positive_count = sum(1 for r in records if r[2] == 'happy')
        negative_count = sum(1 for r in records if r[2] == 'sad')

        # 简单的健康度计算
        health_score = 100 - (negative_count * 15) + (positive_count * 5)
        health_score = max(0, min(100, health_score))  # 限制在 0-100 之间

        # 提取负面瞬间提醒家长
        sad_moments = [f"[{r[0][11:16]}] 孩子说: '{r[1]}'" for r in records if r[2] == 'sad']

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