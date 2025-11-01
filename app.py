from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
import os
from datetime import datetime

from config import Config
from models import db, User, Document, Review

app = Flask(__name__)
app.config.from_object(Config)

# 初始化扩展
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录以访问该页面'

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# ========== 路由 ==========

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('请输入用户名和密码', 'error')
            return render_template('login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password) and user.is_active:
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误，或账户已被禁用', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('您已成功登出', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    # 只有管理员和评审者可以创建用户
    if not (current_user.is_admin() or current_user.role == 'reviewer'):
        flash('您没有权限访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'reviewer')
        
        if not username or not email or not password:
            flash('请填写所有必填字段', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('邮箱已被使用', 'error')
            return render_template('register.html')
        
        # 评审者只能创建评审者
        if current_user.role == 'reviewer' and role == 'admin':
            role = 'reviewer'
        
        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('用户创建成功', 'success')
        return redirect(url_for('user_management'))
    
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin():
        # 管理员视图：所有文档和统计
        documents = Document.query.order_by(Document.created_at.desc()).all()
        total_docs = Document.query.count()
        pending_docs = Document.query.filter_by(status='pending').count()
        completed_docs = Document.query.filter_by(status='completed').count()
        
        return render_template('dashboard_admin.html', 
                             documents=documents,
                             total_docs=total_docs,
                             pending_docs=pending_docs,
                             completed_docs=completed_docs)
    else:
        # 评审者视图：待评审文档和已评审文档
        all_documents = Document.query.order_by(Document.created_at.desc()).all()
        my_reviews = Review.query.filter_by(reviewer_id=current_user.id).all()
        reviewed_doc_ids = {r.document_id for r in my_reviews}
        
        pending_docs = [doc for doc in all_documents if doc.id not in reviewed_doc_ids]
        reviewed_docs = [doc for doc in all_documents if doc.id in reviewed_doc_ids]
        
        return render_template('dashboard_reviewer.html',
                             pending_docs=pending_docs,
                             reviewed_docs=reviewed_docs)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if not current_user.is_admin():
        flash('只有管理员可以上传文档', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('请选择文件', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        
        if file.filename == '':
            flash('请选择文件', 'error')
            return redirect(request.url)
        
        if not title:
            flash('请输入文档标题', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # 添加时间戳避免文件名冲突
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            document = Document(
                title=title,
                description=description,
                filename=file.filename,
                filepath=filepath,
                uploader_id=current_user.id,
                status='pending'
            )
            db.session.add(document)
            db.session.commit()
            
            flash('文档上传成功', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('不支持的文件类型', 'error')
    
    return render_template('upload.html')

@app.route('/document/<int:doc_id>')
@login_required
def view_document(doc_id):
    document = Document.query.get_or_404(doc_id)
    
    # 获取所有评审
    reviews = Review.query.filter_by(document_id=doc_id).all()
    
    # 检查当前用户是否已评审
    user_review = Review.query.filter_by(
        document_id=doc_id,
        reviewer_id=current_user.id
    ).first()
    
    return render_template('document_detail.html',
                         document=document,
                         reviews=reviews,
                         user_review=user_review,
                         average_score=document.get_average_score())

@app.route('/download/<int:doc_id>')
@login_required
def download_document(doc_id):
    document = Document.query.get_or_404(doc_id)
    directory = os.path.dirname(document.filepath)
    filename = os.path.basename(document.filepath)
    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/review/<int:doc_id>', methods=['GET', 'POST'])
@login_required
def review_document(doc_id):
    if current_user.is_admin():
        flash('管理员不能进行评审', 'error')
        return redirect(url_for('view_document', doc_id=doc_id))
    
    document = Document.query.get_or_404(doc_id)
    
    # 检查是否已评审
    review = Review.query.filter_by(
        document_id=doc_id,
        reviewer_id=current_user.id
    ).first()
    
    if request.method == 'POST':
        score = request.form.get('score')
        comment = request.form.get('comment', '').strip()
        
        try:
            score = float(score)
            if score < 0 or score > 100:
                flash('评分必须在0-100之间', 'error')
                return render_template('review.html', document=document, review=review)
        except (ValueError, TypeError):
            flash('请输入有效的评分', 'error')
            return render_template('review.html', document=document, review=review)
        
        if review:
            # 更新已有评审
            review.score = score
            review.comment = comment
            review.status = 'completed'
            review.updated_at = datetime.utcnow()
        else:
            # 创建新评审
            review = Review(
                document_id=doc_id,
                reviewer_id=current_user.id,
                score=score,
                comment=comment,
                status='completed'
            )
            db.session.add(review)
        
        # 更新文档状态
        db.session.flush()  # 确保review已保存到数据库
        review_count = document.get_review_count()
        if review_count > 0:
            document.status = 'reviewing'
        
        db.session.commit()
        flash('评审提交成功', 'success')
        return redirect(url_for('view_document', doc_id=doc_id))
    
    return render_template('review.html', document=document, review=review)

@app.route('/users')
@login_required
def user_management():
    if not (current_user.is_admin() or current_user.role == 'reviewer'):
        flash('您没有权限访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('user_management.html', users=users)

@app.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # 权限检查
    if not (current_user.is_admin() or (current_user.role == 'reviewer' and current_user.id == user_id)):
        flash('您没有权限修改此用户', 'error')
        return redirect(url_for('user_management'))
    
    if request.method == 'POST':
        # 只能修改自己的信息，或管理员修改任何用户
        if current_user.id == user_id or current_user.is_admin():
            password = request.form.get('password', '').strip()
            email = request.form.get('email', '').strip()
            
            if email:
                # 检查邮箱是否已被其他用户使用
                existing_user = User.query.filter_by(email=email).first()
                if existing_user and existing_user.id != user_id:
                    flash('邮箱已被使用', 'error')
                    return render_template('edit_user.html', user=user)
                user.email = email
            
            if password:
                user.set_password(password)
            
            # 只有管理员可以修改角色和状态
            if current_user.is_admin():
                role = request.form.get('role')
                is_active = request.form.get('is_active') == 'on'
                if role:
                    user.role = role
                user.is_active = is_active
            
            db.session.commit()
            flash('用户信息更新成功', 'success')
            
            if current_user.id == user_id:
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('user_management'))
    
    return render_template('edit_user.html', user=user)

@app.route('/api/document/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_document(doc_id):
    if not current_user.is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403
    
    document = Document.query.get_or_404(doc_id)
    
    # 删除文件
    if os.path.exists(document.filepath):
        os.remove(document.filepath)
    
    db.session.delete(document)
    db.session.commit()
    
    return jsonify({'success': True, 'message': '文档删除成功'})

# ========== 错误处理 ==========

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    flash('文件过大，最大允许16MB', 'error')
    return redirect(url_for('upload'))

# ========== 初始化 ==========

def init_db():
    """初始化数据库"""
    with app.app_context():
        db.create_all()
        
        # 创建默认管理员账户
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@example.com', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('默认管理员账户已创建: username=admin, password=admin123')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)

