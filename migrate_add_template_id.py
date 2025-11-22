"""
数据库迁移脚本：为 review_events 表添加 template_id 字段
"""
import sqlite3
import os

db_path = 'database.db'

if not os.path.exists(db_path):
    print(f"数据库文件 {db_path} 不存在，无需迁移")
    exit(0)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查 review_events 表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_events'")
    if not cursor.fetchone():
        print("review_events 表不存在，无需迁移")
        conn.close()
        exit(0)
    
    # 检查 template_id 字段是否已存在
    cursor.execute("PRAGMA table_info(review_events)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'template_id' in columns:
        print("review_events.template_id 字段已存在，无需迁移")
        conn.close()
        exit(0)
    
    # 添加 template_id 字段
    print("正在为 review_events 表添加 template_id 字段...")
    cursor.execute("ALTER TABLE review_events ADD COLUMN template_id INTEGER")
    conn.commit()
    print("[OK] 成功添加 template_id 字段")
    
    conn.close()
    print("迁移完成！")
    
except sqlite3.OperationalError as e:
    print(f"迁移失败: {e}")
    print("\n如果遇到 'no such column' 或其他错误，建议：")
    print("1. 备份 database.db 文件")
    print("2. 删除 database.db 文件")
    print("3. 重新运行应用以创建新数据库")
except Exception as e:
    print(f"发生错误: {e}")

