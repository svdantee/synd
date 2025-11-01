# 文档评审系统

一个基于Flask和SQLite的完整文档评审管理系统，支持管理员上传文档、评审者进行评分、用户管理等功能。

## 功能特性

### 管理员功能
- ✅ 文档上传（支持PDF、DOC、DOCX、TXT、XLSX、XLS格式）
- ✅ 查看所有文档列表和评审结果
- ✅ 文档统计（总数、待评审、已完成）
- ✅ 用户管理（创建、编辑用户信息）
- ✅ 删除文档

### 评审者功能
- ✅ 查看待评审文档列表
- ✅ 查看已评审文档列表
- ✅ 对文档进行评审打分（0-100分）
- ✅ 添加评审意见
- ✅ 修改已有评审
- ✅ 创建新用户（只能创建评审者）
- ✅ 修改自己的密码和信息

### 用户管理功能
- ✅ 用户注册/创建
- ✅ 密码修改
- ✅ 用户信息编辑
- ✅ 账户激活/禁用（管理员）
- ✅ 角色管理（管理员/评审者）

## 技术栈

- **后端**: Python 3.8+, Flask 3.0.0
- **数据库**: SQLite（支持100+用户）
- **前端**: HTML5, CSS3, JavaScript
- **认证**: Flask-Login
- **文件处理**: Werkzeug

## 项目结构

```
synd/
├── app.py                 # 主应用文件
├── config.py              # 配置文件
├── models.py              # 数据库模型
├── requirements.txt       # 依赖包列表
├── README.md             # 项目说明
├── database.db           # SQLite数据库（自动生成）
├── uploads/              # 上传文件目录（自动生成）
├── templates/            # HTML模板
│   ├── base.html
│   ├── login.html
│   ├── dashboard_admin.html
│   ├── dashboard_reviewer.html
│   ├── upload.html
│   ├── document_detail.html
│   ├── review.html
│   ├── user_management.html
│   ├── register.html
│   ├── edit_user.html
│   ├── 404.html
│   └── 500.html
└── static/               # 静态文件
    ├── css/
    │   └── style.css
    └── js/
        └── main.js
```

## 安装步骤

### 1. 环境要求
- Python 3.8 或更高版本
- pip 包管理器

### 2. 创建虚拟环境（推荐）

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 初始化数据库

运行应用会自动创建数据库和默认管理员账户：

```bash
python app.py
```

### 5. 访问应用

打开浏览器访问：`http://localhost:5000`

## 默认账户

系统首次运行会自动创建默认管理员账户：
- **用户名**: `admin`
- **密码**: `admin123`

**⚠️ 重要：首次登录后请立即修改默认密码！**

## 使用说明

### 管理员操作流程

1. **登录系统**
   - 使用管理员账户登录

2. **上传文档**
   - 点击"上传文档"
   - 填写文档标题和描述
   - 选择文件（最大16MB）
   - 提交上传

3. **查看评审结果**
   - 在控制台查看所有文档
   - 点击文档标题查看详细信息
   - 查看评审列表和平均分

4. **用户管理**
   - 点击"用户管理"查看所有用户
   - 点击"创建新用户"添加新用户
   - 点击"编辑"修改用户信息

### 评审者操作流程

1. **登录系统**
   - 使用评审者账户登录

2. **查看待评审文档**
   - 在控制台查看"待评审文档"列表
   - 点击"开始评审"进行评分

3. **进行评审**
   - 下载并查看文档
   - 输入评分（0-100分）
   - 填写评审意见
   - 提交评审

4. **查看已评审文档**
   - 在控制台查看"已评审文档"列表
   - 可以修改已有评审

## 数据库说明

系统使用SQLite数据库，包含以下表：

- **users**: 用户表
  - id, username, email, password_hash, role, created_at, is_active

- **documents**: 文档表
  - id, title, description, filename, filepath, uploader_id, status, created_at, updated_at

- **reviews**: 评审表
  - id, document_id, reviewer_id, score, comment, status, created_at, updated_at

## 配置说明

主要配置项在 `config.py` 中：

- `SECRET_KEY`: Flask密钥（生产环境请修改）
- `SQLALCHEMY_DATABASE_URI`: 数据库连接
- `UPLOAD_FOLDER`: 上传文件目录
- `MAX_CONTENT_LENGTH`: 最大文件大小（16MB）
- `ALLOWED_EXTENSIONS`: 允许的文件类型

## 安全建议

1. **修改默认密码**: 首次登录后立即修改管理员密码
2. **更改SECRET_KEY**: 在生产环境中设置强密钥
3. **限制文件大小**: 根据需要调整MAX_CONTENT_LENGTH
4. **定期备份**: 定期备份 `database.db` 和 `uploads/` 目录
5. **HTTPS**: 生产环境建议使用HTTPS

## 生产环境部署

1. 设置环境变量：
```bash
export SECRET_KEY='your-secret-key-here'
export FLASK_ENV=production
```

2. 使用生产级WSGI服务器（如Gunicorn）：
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

3. 使用Nginx作为反向代理

## 常见问题

### Q: 如何重置管理员密码？
A: 可以直接修改数据库，或创建一个新的管理员账户。

### Q: 支持多少用户？
A: SQLite可以轻松支持100+用户，如果用户量更大，建议迁移到PostgreSQL或MySQL。

### Q: 如何备份数据？
A: 复制 `database.db` 文件和 `uploads/` 目录即可。

### Q: 文件上传失败？
A: 检查 `uploads/` 目录权限，确保应用有写入权限。

## 许可证

MIT License

## 开发者

如有问题或建议，欢迎提交Issue。

