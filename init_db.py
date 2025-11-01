"""
数据库初始化脚本
用于初始化数据库和创建默认管理员账户
"""
from app import app, db
from models import User

def init_database():
    """初始化数据库"""
    with app.app_context():
        # 创建所有表
        db.create_all()
        print("✓ 数据库表创建成功")
        
        # 创建默认管理员账户
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@example.com', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✓ 默认管理员账户已创建")
            print("  用户名: admin")
            print("  密码: admin123")
            print("  ⚠️  请首次登录后立即修改密码！")
        else:
            print("✓ 管理员账户已存在，跳过创建")
        
        print("\n数据库初始化完成！")
        print("现在可以运行 'python app.py' 启动应用")

if __name__ == '__main__':
    init_database()

