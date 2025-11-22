from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
import os
from datetime import datetime, timedelta, timezone

from config import Config
from models import db, User, Document, Review, Setting, Announcement, Instruction, ScoringTemplate, TemplateDimension, ReviewDetail, ReviewerTeacher, ReviewEvent, EventTeacher, EventReviewer

# 北京时间时区（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_now():
    """获取当前北京时间（UTC+8）"""
    return datetime.now(BEIJING_TZ)

def utc_to_beijing(utc_dt):
    """将 UTC 时间转换为北京时间"""
    if utc_dt is None:
        return None
    if utc_dt.tzinfo is None:
        # 如果没有时区信息，假设是 UTC
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(BEIJING_TZ)

def beijing_to_utc(beijing_dt):
    """将北京时间转换为 UTC 时间（用于存储）"""
    if beijing_dt is None:
        return None
    if beijing_dt.tzinfo is None:
        # 如果没有时区信息，假设是北京时间
        beijing_dt = beijing_dt.replace(tzinfo=BEIJING_TZ)
    return beijing_dt.astimezone(timezone.utc).replace(tzinfo=None)

app = Flask(__name__)
app.config.from_object(Config)

# 添加 Jinja2 过滤器：将 UTC 时间转换为北京时间显示
@app.template_filter('beijing_time')
def beijing_time_filter(dt):
    """在模板中将 UTC 时间转换为北京时间显示"""
    if dt is None:
        return None
    beijing_dt = utc_to_beijing(dt)
    return beijing_dt.strftime('%Y-%m-%d %H:%M:%S') if beijing_dt else None

@app.template_filter('beijing_time_short')
def beijing_time_short_filter(dt):
    """在模板中将 UTC 时间转换为北京时间显示（短格式）"""
    if dt is None:
        return None
    beijing_dt = utc_to_beijing(dt)
    return beijing_dt.strftime('%Y-%m-%d %H:%M') if beijing_dt else None

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

# Helpers
def get_settings() -> Setting:
    settings = Setting.query.first()
    if not settings:
        settings = Setting()
        db.session.add(settings)
        db.session.commit()
    return settings

# ========== 路由 ==========

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    # 未登录用户直接重定向到登录页
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
            # 检查教师和评审员是否填写了个人信息（手机号、邮箱）
            if user.role in ['teacher', 'reviewer']:
                if not user.phone or not user.email:
                    # 未填写完整信息，跳转到个人信息补充页面
                    next_page = request.args.get('next')
                    return redirect(url_for('complete_profile', next=next_page))
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
def register():
    # 禁止自行注册，只有管理员可以创建账号
    flash('账号需要通过管理员创建，请联系管理员', 'error')
    return redirect(url_for('login'))

@app.route('/admin/create_user', methods=['GET', 'POST'])
@login_required
def admin_create_user():
    """管理员创建用户（无需审批，立即激活）"""
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'reviewer')
        # 新建用户默认激活
        is_active = True
        
        if not username or not email or not password:
            flash('请填写所有必填字段', 'error')
            return render_template('admin_create_user.html', back_url=url_for('user_management'))
        
        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'error')
            return render_template('admin_create_user.html', back_url=url_for('user_management'))
        
        if User.query.filter_by(email=email).first():
            flash('邮箱已被使用', 'error')
            return render_template('admin_create_user.html', back_url=url_for('user_management'))
        
        user = User(username=username, email=email, role=role, is_active=is_active)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('用户创建成功', 'success')
        return redirect(url_for('user_management'))
    
    return render_template('admin_create_user.html')

@app.route('/dashboard')
@login_required
def dashboard():
    # 检查教师和评审员是否填写了个人信息
    if current_user.role in ['teacher', 'reviewer']:
        if not current_user.phone or not current_user.email:
            return redirect(url_for('complete_profile'))
    
    if current_user.is_admin():
        # 管理员视图：显示活动列表
        events = ReviewEvent.query.order_by(ReviewEvent.created_at.desc()).all()
        # 统计每个活动的文档数
        event_stats = {}
        for event in events:
            doc_count = Document.query.filter_by(event_id=event.id).count()
            completed_count = Document.query.filter_by(event_id=event.id, status='completed').count()
            event_stats[event.id] = {
                'total': doc_count,
                'completed': completed_count
            }
        
        return render_template('dashboard_admin.html', 
                             events=events,
                             event_stats=event_stats,
                             back_url=url_for('dashboard'))
    elif current_user.role == 'reviewer':
        # 评审者视图：显示评审活动选择页面（与教师相同）
        # 获取对该评审员可见的活动
        all_events = ReviewEvent.query.filter_by(is_active=True).order_by(ReviewEvent.created_at.desc()).all()
        events = []
        for ev in all_events:
            cnt = EventReviewer.query.filter_by(event_id=ev.id).count()
            if cnt == 0 or EventReviewer.query.filter_by(event_id=ev.id, reviewer_id=current_user.id).first():
                events.append(ev)
        return render_template('dashboard_reviewer.html', events=events)
    elif current_user.role == 'teacher':
        # 教师视图：显示评审活动选择页面
        # 获取对该教师可见的活动
        all_events = ReviewEvent.query.filter_by(is_active=True).order_by(ReviewEvent.created_at.desc()).all()
        events = []
        for ev in all_events:
            cnt = EventTeacher.query.filter_by(event_id=ev.id).count()
            if cnt == 0 or EventTeacher.query.filter_by(event_id=ev.id, teacher_id=current_user.id).first():
                events.append(ev)
        return render_template('dashboard_teacher.html', events=events)
    else:
        # 未知角色，重定向到登录页
        flash('未知的用户角色', 'error')
        return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    # 仅教师可上传作品，管理员不可以上传
    if not getattr(current_user, 'role', None) == 'teacher':
        flash('只有教师可以上传作品', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('请选择文件', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        doc_id = request.form.get('doc_id', type=int)
        
        # 检查是否为编辑模式
        existing_doc = Document.query.get(doc_id) if doc_id else None
        is_edit = existing_doc and existing_doc.uploader_id == current_user.id
        
        # 编辑模式下，如果没有选择新文件，则只更新标题和描述
        if is_edit and file.filename == '':
            if not title:
                flash('请输入文档标题', 'error')
                return redirect(request.url)
            existing_doc.title = title
            existing_doc.description = description
            existing_doc.updated_at = datetime.utcnow()
            db.session.commit()
            flash('文档信息已更新', 'success')
            event_id = request.form.get('event_id', type=int)
            if event_id:
                return redirect(url_for('teacher_event_detail', event_id=event_id))
            return redirect(url_for('dashboard'))
        
        if not is_edit and file.filename == '':
            flash('请选择文件', 'error')
            return redirect(request.url)
        
        if not title:
            flash('请输入文档标题', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            # 选择事件
            event_id = request.form.get('event_id', type=int)
            event = ReviewEvent.query.get(event_id) if event_id else None
            
            # 检查上传截止时间
            if event and event.upload_deadline:
                now = beijing_now()
                deadline = utc_to_beijing(event.upload_deadline)
                if now > deadline:
                    flash('该活动的上传截止时间已过，无法上传或更新作品', 'error')
                    return redirect(url_for('dashboard'))
            
            filename = secure_filename(file.filename)
            # 添加时间戳避免文件名冲突
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # 选择评分模板：优先使用活动关联的模板，否则使用全局模板
            template = None
            if event and event.template:
                template = event.template
            else:
                settings = get_settings()
                template = settings.active_template
            
            if is_edit:
                # 更新现有文档
                # 删除旧文件
                if os.path.exists(existing_doc.filepath):
                    os.remove(existing_doc.filepath)
                existing_doc.title = title
                existing_doc.description = description
                existing_doc.filename = file.filename
                existing_doc.filepath = filepath
                existing_doc.template_id = template.id if template else None
                existing_doc.updated_at = datetime.utcnow()
                db.session.commit()
                flash('文档更新成功', 'success')
            else:
                # 创建新文档
                document = Document(
                    title=title,
                    description=description,
                    filename=file.filename,
                    filepath=filepath,
                    uploader_id=current_user.id,
                    status='pending',
                    template_id=template.id if template else None,
                    event_id=event.id if event else None
                )
                db.session.add(document)
                db.session.commit()
                flash('文档上传成功', 'success')
            
            # 如果是从活动详情页跳转的，返回活动详情页
            if event_id:
                return redirect(url_for('teacher_event_detail', event_id=event_id))
            return redirect(url_for('dashboard'))
        else:
            flash('不支持的文件类型', 'error')
    
    # 传入可选事件列表（仅活跃）
    # 教师仅能看到对自己可见或未设置白名单的活动
    all_events = ReviewEvent.query.filter_by(is_active=True).order_by(ReviewEvent.created_at.desc()).all()
    events = []
    if getattr(current_user, 'role', None) == 'teacher':
        for ev in all_events:
            cnt = EventTeacher.query.filter_by(event_id=ev.id).count()
            if cnt == 0 or EventTeacher.query.filter_by(event_id=ev.id, teacher_id=current_user.id).first():
                events.append(ev)
    else:
        events = all_events
    
    # 检查是否为编辑模式
    doc_id = request.args.get('doc_id', type=int)
    existing_doc = None
    if doc_id:
        existing_doc = Document.query.get(doc_id)
        if not existing_doc or existing_doc.uploader_id != current_user.id:
            existing_doc = None
    
    return render_template('upload.html', events=events, existing_doc=existing_doc, back_url=url_for('dashboard'))

@app.route('/document/<int:doc_id>', methods=['GET', 'POST'])
@login_required
def view_document(doc_id):
    document = Document.query.get_or_404(doc_id)
    
    # 获取action参数（用于判断是否直接进入编辑模式）
    action = request.args.get('action', '')
    
    # 如果是评审者且提交了评分更新
    if request.method == 'POST' and current_user.role == 'reviewer':
        # 检查活动时间状态
        now = beijing_now()
        if document.event:
            event_start_time = utc_to_beijing(document.event.start_time) if document.event.start_time else None
            event_end_time = utc_to_beijing(document.event.end_time) if document.event.end_time else None
            if event_start_time and now < event_start_time:
                flash('该活动的评审尚未开始', 'error')
                return redirect(url_for('view_document', doc_id=doc_id))
            if event_end_time and now > event_end_time:
                flash('该活动的评审已结束', 'error')
                return redirect(url_for('view_document', doc_id=doc_id))
        
        # 获取当前用户的评审，如果不存在则创建
        user_review = Review.query.filter_by(
            document_id=doc_id,
            reviewer_id=current_user.id
        ).first()
        
        if not user_review:
            # 创建新评审
            user_review = Review(document_id=doc_id, reviewer_id=current_user.id, status='pending')
            db.session.add(user_review)
            db.session.flush()
        elif user_review.status == 'completed':
            # 已完成评审可以修改（在活动进行中）
            pass
        
        # 获取模板维度
        if document.template:
            dimensions = document.template.dimensions.all()
        else:
            dimensions = []
        
        if not dimensions:
            flash('未设置评分模板，无法提交评审', 'error')
            return redirect(url_for('view_document', doc_id=doc_id))
        
        # 更新评审
        total_weight = sum(d.weight for d in dimensions) or 1.0
        weighted_total = 0.0
        
        # 清理旧明细
        ReviewDetail.query.filter_by(review_id=user_review.id).delete()
        
        # 收集维度分
        for dim in dimensions:
            field_name = f"dim_{dim.id}_score"
            cmt_name = f"dim_{dim.id}_comment"
            try:
                dim_score = float(request.form.get(field_name, ''))
            except ValueError:
                flash(f'维度「{dim.name}」评分无效', 'error')
                return redirect(url_for('view_document', doc_id=doc_id))
            if dim_score < 0 or dim_score > 100:
                flash(f'维度「{dim.name}」评分必须在0-100之间', 'error')
                return redirect(url_for('view_document', doc_id=doc_id))
            weighted_total += (dim_score * dim.weight)
            detail = ReviewDetail(review_id=user_review.id, dimension_id=dim.id, score=dim_score,
                                  comment=request.form.get(cmt_name, '').strip())
            db.session.add(detail)
        
        # 计算总分
        final_score = weighted_total / total_weight
        user_review.score = round(final_score, 2)
        user_review.comment = request.form.get('comment', '').strip()
        user_review.status = 'completed'
        user_review.updated_at = beijing_now().replace(tzinfo=None)
        
        # 更新文档状态：如果有评审完成，更新文档状态
        # 查询该文档的所有评审记录
        all_reviews = Review.query.filter_by(document_id=doc_id).all()
        completed_reviews = [r for r in all_reviews if r.status == 'completed']
        
        if len(completed_reviews) > 0:
            # 如果有评审完成，将状态从pending改为reviewing（已评审）
            if document.status == 'pending':
                document.status = 'reviewing'
                document.updated_at = datetime.utcnow()
        
        # 如果当前用户是评审者且文档属于某个活动，保存返回URL到session
        if current_user.role == 'reviewer' and document.event_id:
            from flask import session
            session['reviewer_back_url'] = url_for('reviewer_event_detail', event_id=document.event_id)
        
        db.session.commit()
        flash('评审已保存', 'success')
        
        # 保持在当前页面，不跳转
        return redirect(url_for('view_document', doc_id=doc_id))
    
    # GET 请求：显示文档详情
    # 获取所有评审
    reviews = Review.query.filter_by(document_id=doc_id).all()
    settings = get_settings()
    
    # 检查当前用户是否已评审
    user_review = Review.query.filter_by(
        document_id=doc_id,
        reviewer_id=current_user.id
    ).first()
    
    # 获取当前用户的评审详情（如果是评审者）
    user_review_details = {}
    dimensions = []
    if document.template:
        dimensions = document.template.dimensions.all()
    if user_review:
        for detail in user_review.details:
            user_review_details[detail.dimension_id] = {
                'score': detail.score,
                'comment': detail.comment
            }
    
    # 检查活动时间状态（使用北京时间）
    event_status = None
    event_start_time = None
    event_end_time = None
    if document.event:
        now = beijing_now()
        # 将 UTC 时间转换为北京时间
        event_start_time = utc_to_beijing(document.event.start_time) if document.event.start_time else None
        event_end_time = utc_to_beijing(document.event.end_time) if document.event.end_time else None
        if event_start_time and now < event_start_time:
            event_status = 'not_started'
        elif event_end_time and now > event_end_time:
            event_status = 'ended'
        else:
            event_status = 'active'
    
    # 获取action参数（用于判断是否直接进入编辑模式）
    action = request.args.get('action', '')
    
    # 确定返回URL：优先使用URL参数中的back_url，否则根据角色和文档所属活动确定
    back_url = request.args.get('back_url', '')
    if not back_url:
        back_url = url_for('dashboard')
        if current_user.role == 'reviewer' and document.event_id:
            # 评审者从活动详情页进入，返回活动详情页
            back_url = url_for('reviewer_event_detail', event_id=document.event_id)
        elif current_user.role == 'teacher' and document.event_id:
            # 教师从活动详情页进入，返回活动详情页
            back_url = url_for('teacher_event_detail', event_id=document.event_id)
        elif current_user.is_admin() and document.event_id:
            # 管理员从活动文档列表页进入，返回活动文档列表页
            back_url = url_for('admin_event_documents', event_id=document.event_id)
    
    return render_template('document_detail.html',
                         document=document,
                         reviews=reviews,
                         user_review=user_review,
                         user_review_details=user_review_details,
                         dimensions=dimensions,
                         average_score=document.get_average_score(),
                         show_teacher_name=settings.show_teacher_name,
                         event_status=event_status,
                         event_start_time=event_start_time,
                         event_end_time=event_end_time,
                         action=action,
                         back_url=back_url)

@app.route('/download/<int:doc_id>')
@login_required
def download_document(doc_id):
    document = Document.query.get_or_404(doc_id)
    directory = os.path.dirname(document.filepath)
    filename = os.path.basename(document.filepath)
    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/preview/<int:doc_id>')
@login_required
def preview_document(doc_id):
    """在线预览PDF"""
    document = Document.query.get_or_404(doc_id)
    if not document.filename.lower().endswith('.pdf'):
        flash('仅支持预览PDF文件', 'error')
        return redirect(url_for('view_document', doc_id=doc_id))
    directory = os.path.dirname(document.filepath)
    filename = os.path.basename(document.filepath)
    # inline 显示
    return send_from_directory(directory, filename, as_attachment=False, mimetype='application/pdf')

@app.route('/review/<int:doc_id>', methods=['GET', 'POST'])
@login_required
def review_document(doc_id):
    # 只有评审者可以进行评审
    if current_user.is_admin():
        flash('管理员不能进行评审', 'error')
        return redirect(url_for('view_document', doc_id=doc_id))
    if current_user.role != 'reviewer':
        flash('只有评审者可以进行评审', 'error')
        return redirect(url_for('view_document', doc_id=doc_id))
    
    document = Document.query.get_or_404(doc_id)
    # 仅按活动窗口限制评审（如果文档归属某活动）
    now = beijing_now()
    if document.event:
        # 将 UTC 时间转换为北京时间进行比较
        start_time = utc_to_beijing(document.event.start_time) if document.event.start_time else None
        end_time = utc_to_beijing(document.event.end_time) if document.event.end_time else None
        if start_time and now < start_time:
            flash('该活动的评审尚未开始', 'error')
            return redirect(url_for('view_document', doc_id=doc_id))
        if end_time and now > end_time:
            flash('该活动的评审已结束', 'error')
            return redirect(url_for('view_document', doc_id=doc_id))
    
    # 检查是否已评审
    review = Review.query.filter_by(
        document_id=doc_id,
        reviewer_id=current_user.id
    ).first()
    # 已完成评审不能修改
    if review and review.status == 'completed' and request.method == 'POST':
        flash('已完成的评审无法更改', 'error')
        return redirect(url_for('view_document', doc_id=doc_id))
    
    if request.method == 'POST':
        # 多维度评分
        overall_comment = request.form.get('comment', '').strip()
        if document.template:
            dimensions = document.template.dimensions.all()
        else:
            dimensions = []
        if not dimensions:
            flash('未设置评分模板，无法提交评审', 'error')
            return redirect(url_for('view_document', doc_id=doc_id))
        total_weight = sum(d.weight for d in dimensions) or 1.0
        weighted_total = 0.0
        # 生成或更新Review
        if not review:
            review = Review(document_id=doc_id, reviewer_id=current_user.id, status='pending')
            db.session.add(review)
            db.session.flush()
        # 清理旧明细（如果存在且未完成）
        if review.status != 'completed':
            ReviewDetail.query.filter_by(review_id=review.id).delete()
        # 收集维度分
        for dim in dimensions:
            field_name = f"dim_{dim.id}_score"
            cmt_name = f"dim_{dim.id}_comment"
            try:
                dim_score = float(request.form.get(field_name, ''))
            except ValueError:
                flash(f'维度「{dim.name}」评分无效', 'error')
                return render_template('review.html', document=document, review=review, dimensions=dimensions)
            if dim_score < 0 or dim_score > 100:
                flash(f'维度「{dim.name}」评分必须在0-100之间', 'error')
                return render_template('review.html', document=document, review=review, dimensions=dimensions)
            weighted_total += (dim_score * dim.weight)
            detail = ReviewDetail(review_id=review.id, dimension_id=dim.id, score=dim_score,
                                  comment=request.form.get(cmt_name, '').strip())
            db.session.add(detail)
        # 计算总分（按权重平均到100）
        final_score = weighted_total / total_weight
        review.score = round(final_score, 2)
        review.comment = overall_comment
        review.status = 'completed'
        review.updated_at = beijing_now().replace(tzinfo=None)  # 存储为 UTC（naive datetime）
        
        # 更新文档状态
        db.session.flush()
        review_count = document.get_review_count()
        if review_count > 0:
            document.status = 'reviewing'
        
        db.session.commit()
        flash('评审提交成功', 'success')
        return redirect(url_for('view_document', doc_id=doc_id))
    
    # 传递模板维度到前端（按排序）
    if document.template:
        dimensions = document.template.dimensions.all()
    else:
        dimensions = []
    return render_template('review.html', document=document, review=review, dimensions=dimensions, back_url=url_for('view_document', doc_id=doc_id))

@app.route('/users')
@login_required
def user_management():
    if not (current_user.is_admin() or current_user.role == 'reviewer'):
        flash('您没有权限访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    # 获取查询参数
    search_username = request.args.get('search_username', '').strip()
    filter_role = request.args.get('filter_role', '')
    filter_status = request.args.get('filter_status', '')
    sort_by = request.args.get('sort_by', 'id')  # 默认按id排序
    sort_order = request.args.get('sort_order', 'desc')  # 默认倒序
    
    # 构建查询
    query = User.query
    
    # 用户名模糊查询
    if search_username:
        query = query.filter(User.username.like(f'%{search_username}%'))
    
    # 角色筛选
    if filter_role:
        query = query.filter(User.role == filter_role)
    
    # 状态筛选
    if filter_status:
        if filter_status == 'active':
            query = query.filter(User.is_active == True)
        elif filter_status == 'inactive':
            query = query.filter(User.is_active == False)
    
    # 排序
    if sort_by == 'created_at':
        if sort_order == 'desc':
            query = query.order_by(User.created_at.desc())
        else:
            query = query.order_by(User.created_at.asc())
    else:  # 默认按id排序
        if sort_order == 'desc':
            query = query.order_by(User.id.desc())
        else:
            query = query.order_by(User.id.asc())
    
    users = query.all()
    pending_count = User.query.filter_by(is_active=False).count()
    
    return render_template('user_management.html', 
                         users=users, 
                         pending_count=pending_count, 
                         search_username=search_username,
                         filter_role=filter_role,
                         filter_status=filter_status,
                         sort_by=sort_by,
                         sort_order=sort_order,
                         back_url=url_for('dashboard'))

@app.route('/complete-profile', methods=['GET', 'POST'])
@login_required
def complete_profile():
    """个人信息补充页面（教师和评审员首次登录时填写）"""
    # 只有教师和评审员需要填写
    if current_user.role not in ['teacher', 'reviewer']:
        return redirect(url_for('dashboard'))
    
    # 如果已经填写完整，直接跳转
    if current_user.phone and current_user.email:
        next_page = request.args.get('next')
        return redirect(next_page) if next_page else redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        
        if not username:
            flash('请输入用户名', 'error')
            return render_template('complete_profile.html')
        if not phone:
            flash('请输入手机号', 'error')
            return render_template('complete_profile.html')
        if not email:
            flash('请输入邮箱', 'error')
            return render_template('complete_profile.html')
        
        # 验证邮箱格式（简单验证）
        if '@' not in email:
            flash('邮箱格式不正确', 'error')
            return render_template('complete_profile.html')
        
        # 检查用户名是否已被其他用户使用
        existing_user = User.query.filter(User.username == username, User.id != current_user.id).first()
        if existing_user:
            flash('该用户名已被其他用户使用', 'error')
            return render_template('complete_profile.html')
        
        # 检查邮箱是否已被其他用户使用
        existing_user = User.query.filter(User.email == email, User.id != current_user.id).first()
        if existing_user:
            flash('该邮箱已被其他用户使用', 'error')
            return render_template('complete_profile.html')
        
        current_user.username = username
        current_user.phone = phone
        current_user.email = email
        db.session.commit()
        
        flash('个人信息已保存', 'success')
        next_page = request.args.get('next')
        return redirect(next_page) if next_page else redirect(url_for('dashboard'))
    
    return render_template('complete_profile.html')

@app.route('/teacher/event/<int:event_id>')
@login_required
def teacher_event_detail(event_id):
    """教师活动详情页面"""
    if current_user.role != 'teacher':
        flash('只有教师可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    event = ReviewEvent.query.get_or_404(event_id)
    
    # 检查活动是否对该教师可见
    cnt = EventTeacher.query.filter_by(event_id=event.id).count()
    if cnt > 0 and not EventTeacher.query.filter_by(event_id=event.id, teacher_id=current_user.id).first():
        flash('您没有权限访问此活动', 'error')
        return redirect(url_for('dashboard'))
    
    # 获取该教师在该活动下上传的所有文档
    documents = Document.query.filter_by(
        event_id=event_id,
        uploader_id=current_user.id
    ).order_by(Document.created_at.desc()).all()
    
    # 检查上传截止时间
    now = beijing_now()
    upload_deadline = utc_to_beijing(event.upload_deadline) if event.upload_deadline else None
    can_upload = True
    if upload_deadline and now > upload_deadline:
        can_upload = False
    
    return render_template('teacher_event_detail.html', 
                         event=event, 
                         documents=documents,
                         can_upload=can_upload,
                         upload_deadline=upload_deadline,
                         now=now)

@app.route('/reviewer/event/<int:event_id>')
@login_required
def reviewer_event_detail(event_id):
    """评审者活动详情页面"""
    if current_user.role != 'reviewer':
        flash('只有评审者可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    event = ReviewEvent.query.get_or_404(event_id)
    
    # 检查活动是否对该评审员可见
    cnt = EventReviewer.query.filter_by(event_id=event.id).count()
    if cnt > 0 and not EventReviewer.query.filter_by(event_id=event.id, reviewer_id=current_user.id).first():
        flash('您没有权限访问此活动', 'error')
        return redirect(url_for('dashboard'))
    
    # 获取筛选参数
    search_title = request.args.get('search_title', '').strip()
    filter_status = request.args.get('filter_status', '')  # 'reviewed' 或 'pending'
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # 如未配置映射，则显示全部（兼容旧行为）
    assigned_teacher_ids = [m.teacher_id for m in current_user.assigned_teachers] if hasattr(current_user, 'assigned_teachers') else []
    query = Document.query.filter_by(event_id=event_id)
    if assigned_teacher_ids:
        query = query.filter(Document.uploader_id.in_(assigned_teacher_ids))
    
    # 构建查询
    all_documents = query.order_by(Document.created_at.desc()).all()
    # 重新查询评审记录，确保获取最新数据
    my_reviews = Review.query.filter_by(reviewer_id=current_user.id).all()
    reviewed_doc_ids = {r.document_id for r in my_reviews}
    
    # 为每个文档添加评审状态和总分
    documents_with_status = []
    for doc in all_documents:
        # 重新查询该文档的评审状态，确保获取最新数据
        user_review = Review.query.filter_by(document_id=doc.id, reviewer_id=current_user.id).first()
        is_reviewed = user_review is not None and user_review.status == 'completed'
        # 获取该文档的总分（当前用户的评审总分，如果已评审）
        total_score = None
        if is_reviewed and user_review:
            total_score = user_review.score
        documents_with_status.append({
            'document': doc,
            'is_reviewed': is_reviewed,
            'status': '已评审' if is_reviewed else '未评审',
            'total_score': total_score
        })
    
    # 应用筛选
    filtered_docs = documents_with_status
    if search_title:
        filtered_docs = [item for item in filtered_docs if search_title.lower() in item['document'].title.lower()]
    if filter_status:
        if filter_status == 'reviewed':
            filtered_docs = [item for item in filtered_docs if item['is_reviewed']]
        elif filter_status == 'pending':
            filtered_docs = [item for item in filtered_docs if not item['is_reviewed']]
    
    # 分页
    total = len(filtered_docs)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_docs = filtered_docs[start:end]
    
    # 计算统计数据
    pending_count = sum(1 for item in documents_with_status if not item['is_reviewed'])
    reviewed_count = sum(1 for item in documents_with_status if item['is_reviewed'])
    total_count = len(documents_with_status)
    
    stats = {
        'pending_count': pending_count,
        'reviewed_count': reviewed_count,
        'total_count': total_count
    }
    
    # 计算分页信息
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('reviewer_event_detail.html',
                         event=event,
                         documents=paginated_docs,
                         stats=stats,
                         search_title=search_title,
                         filter_status=filter_status,
                         page=page,
                         total_pages=total_pages,
                         total=total)

@app.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # 权限检查：只能修改自己的信息，或管理员修改任何用户
    if not (current_user.id == user_id or current_user.is_admin()):
        flash('您没有权限修改此用户', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        
        # 处理密码修改（个人设置专用）
        if action == 'change_password' and current_user.id == user_id:
            old_password = request.form.get('old_password', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            if not old_password or not new_password or not confirm_password:
                flash('请填写完整的密码信息', 'error')
                back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                return render_template('edit_user.html', user=user, back_url=back_url)
            
            if new_password != confirm_password:
                flash('两次输入的新密码不一致', 'error')
                back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                return render_template('edit_user.html', user=user, back_url=back_url)
            
            if len(new_password) < 6:
                flash('新密码长度至少6位', 'error')
                back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                return render_template('edit_user.html', user=user, back_url=back_url)
            
            if not user.check_password(old_password):
                flash('旧密码不正确', 'error')
                back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                return render_template('edit_user.html', user=user, back_url=back_url)
            
            user.set_password(new_password)
            db.session.commit()
            flash('密码修改成功', 'success')
            return redirect(url_for('edit_user', user_id=user_id))
        
        # 处理基本信息修改
        password = request.form.get('password', '').strip()
        old_password = request.form.get('old_password', '').strip()
        email = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        phone = request.form.get('phone', '').strip()
        
        # 如果用户修改自己的信息
        if current_user.id == user_id:
            # 允许修改用户名
            if username and username != user.username:
                # 检查用户名是否已被使用
                existing_user = User.query.filter_by(username=username).first()
                if existing_user:
                    flash('用户名已被使用', 'error')
                    back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                    return render_template('edit_user.html', user=user, back_url=back_url)
                user.username = username
            
            # 如果修改密码，需要验证旧密码（旧版兼容）
            if password:
                if not old_password:
                    flash('修改密码需要输入旧密码', 'error')
                    back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                    return render_template('edit_user.html', user=user, back_url=back_url)
                
                if not user.check_password(old_password):
                    flash('旧密码不正确', 'error')
                    back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                    return render_template('edit_user.html', user=user, back_url=back_url)
                user.set_password(password)
        else:
            # 管理员修改其他用户，不需要旧密码验证
            if password:
                user.set_password(password)
        
        # 邮箱修改（所有用户都可以修改自己的邮箱，管理员可以修改任何用户的邮箱）
        if email:
            # 检查邮箱是否已被其他用户使用
            existing_user = User.query.filter_by(email=email).first()
            if existing_user and existing_user.id != user_id:
                flash('邮箱已被使用', 'error')
                back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                return render_template('edit_user.html', user=user, back_url=back_url)
            user.email = email
        
        # 电话修改（个人设置时电话为必填）
        if current_user.id == user_id:
            if not phone:
                flash('电话为必填项，请填写', 'error')
                back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
                return render_template('edit_user.html', user=user, back_url=back_url)
            user.phone = phone
        else:
            # 管理员修改其他用户，电话可选
            if phone is not None:
                user.phone = phone if phone else None
        
        # 只有管理员可以修改角色，但不能修改自己的角色
        if current_user.is_admin() and current_user.id != user_id:
            role = request.form.get('role')
            if role:
                user.role = role
        
        db.session.commit()
        flash('用户信息更新成功', 'success')
        
        if current_user.id == user_id:
            # 个人设置保存后返回个人设置页面
            return redirect(url_for('edit_user', user_id=user_id))
        else:
            return redirect(url_for('user_management'))
    
    # 确定返回URL
    back_url = url_for('user_management') if current_user.is_admin() else url_for('dashboard')
    return render_template('edit_user.html', user=user, back_url=back_url)

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_user_delete(user_id):
    """删除用户"""
    if not current_user.is_admin():
        flash('只有管理员可以删除用户', 'error')
        return redirect(url_for('dashboard'))
    
    user = User.query.get_or_404(user_id)
    
    # 不能删除自己
    if user.id == current_user.id:
        flash('不能删除自己的账户', 'error')
        return redirect(url_for('user_management'))
    
    # 检查是否有相关数据
    doc_count = Document.query.filter_by(uploader_id=user_id).count()
    review_count = Review.query.filter_by(reviewer_id=user_id).count()
    
    username = user.username
    
    # 删除用户（级联删除相关数据）
    db.session.delete(user)
    db.session.commit()
    
    flash(f'用户 "{username}" 已删除（包含 {doc_count} 个文档和 {review_count} 条评审记录）', 'success')
    return redirect(url_for('user_management'))

@app.route('/admin/users/<int:user_id>/toggle_active', methods=['POST'])
@login_required
def admin_user_toggle_active(user_id):
    """切换用户激活状态"""
    if not current_user.is_admin():
        flash('只有管理员可以修改用户状态', 'error')
        return redirect(url_for('dashboard'))
    
    user = User.query.get_or_404(user_id)
    
    # 不能禁用自己
    if user.id == current_user.id and user.is_active:
        flash('不能禁用自己的账户', 'error')
        return redirect(url_for('user_management'))
    
    user.is_active = not user.is_active
    db.session.commit()
    
    status = '激活' if user.is_active else '禁用'
    flash(f'用户 "{user.username}" 已{status}', 'success')
    return redirect(url_for('user_management'))

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

# ========== 管理功能：设置、公告、说明、模板、结果 ==========
@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    settings = get_settings()
    templates = ScoringTemplate.query.order_by(ScoringTemplate.created_at.desc()).all()
    if request.method == 'POST':
        review_start = request.form.get('review_start', '').strip()
        review_end = request.form.get('review_end', '').strip()
        show_teacher_name = request.form.get('show_teacher_name') == 'on'
        active_template_id = request.form.get('active_template_id')
        # parse datetime
        def parse_dt(s):
            if not s:
                return None
            try:
                # HTML datetime-local uses 'YYYY-MM-DDTHH:MM'
                # 解析为北京时间，然后转换为 UTC 存储
                beijing_dt = datetime.strptime(s, '%Y-%m-%dT%H:%M')
                return beijing_to_utc(beijing_dt)
            except ValueError:
                return None
        settings.review_start = parse_dt(review_start)
        settings.review_end = parse_dt(review_end)
        settings.show_teacher_name = show_teacher_name
        if active_template_id:
            tpl = ScoringTemplate.query.get(int(active_template_id))
            settings.active_template = tpl
        db.session.commit()
        flash('设置已保存', 'success')
        return redirect(url_for('admin_settings'))
    return render_template('admin_settings.html', settings=settings, templates=templates, back_url=url_for('dashboard'))

@app.route('/admin/announcements', methods=['GET', 'POST'])
@login_required
def admin_announcements():
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        is_published = request.form.get('is_published') == 'on'
        if not title or not content:
            flash('标题和内容不能为空', 'error')
        else:
            ann = Announcement(title=title, content=content, is_published=is_published)
            db.session.add(ann)
            db.session.commit()
            flash('公告已发布', 'success')
            return redirect(url_for('admin_announcements'))
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return render_template('admin_announcements.html', announcements=announcements, back_url=url_for('dashboard'))

@app.route('/admin/announcements/<int:ann_id>/delete', methods=['POST'])
@login_required
def delete_announcement(ann_id):
    if not current_user.is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403
    ann = Announcement.query.get_or_404(ann_id)
    db.session.delete(ann)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/instruction', methods=['GET', 'POST'])
def instruction_page():
    instr = Instruction.query.first()
    return render_template('instruction.html', instruction=instr)

@app.route('/admin/instruction', methods=['GET', 'POST'])
@login_required
def admin_instruction():
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    instr = Instruction.query.first()
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if not instr:
            instr = Instruction(content=content)
            db.session.add(instr)
        else:
            instr.content = content
        db.session.commit()
        flash('使用说明已保存', 'success')
        return redirect(url_for('admin_instruction'))
    return render_template('admin_instruction.html', instruction=instr, back_url=url_for('dashboard'))

@app.route('/admin/templates')
@login_required
def admin_templates():
    """评分模板列表页面"""
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    templates = ScoringTemplate.query.order_by(ScoringTemplate.created_at.desc()).all()
    # 为每个模板计算维度数量（因为 dimensions 是 lazy='dynamic' 的查询对象）
    for tpl in templates:
        tpl._dimension_count = tpl.dimensions.count()
    
    return render_template('admin_templates.html', templates=templates, back_url=url_for('dashboard'))

@app.route('/admin/templates/create', methods=['GET', 'POST'])
@login_required
def admin_templates_create():
    """创建评分模板页面"""
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        # 获取维度信息（支持多个维度）
        dimension_names = request.form.getlist('dimension_name[]')
        dimension_descriptions = request.form.getlist('dimension_description[]')
        dimension_weights = request.form.getlist('dimension_weight[]')
        
        if not name:
            flash('模板名称不能为空', 'error')
        elif not dimension_names or not any(d.strip() for d in dimension_names):
            flash('至少需要添加一个评分维度', 'error')
        else:
            # 创建评分模板
            tpl = ScoringTemplate(name=name, description=description, is_active=False)
            db.session.add(tpl)
            db.session.flush()
            
            # 创建维度
            for idx, (dim_name, dim_desc, dim_weight) in enumerate(zip(dimension_names, dimension_descriptions, dimension_weights)):
                dim_name = dim_name.strip()
                if not dim_name:
                    continue
                try:
                    weight = float(dim_weight) if dim_weight.strip() else 1.0
                except ValueError:
                    weight = 1.0
                
                dimension = TemplateDimension(
                    template_id=tpl.id,
                    name=dim_name,
                    description=dim_desc.strip(),
                    weight=weight,
                    order_index=idx
                )
                db.session.add(dimension)
            
            db.session.commit()
            flash('模板已创建，评分维度已设置', 'success')
            return redirect(url_for('admin_templates'))
    
    return render_template('admin_templates_create.html', back_url=url_for('admin_templates'))

@app.route('/admin/templates/<int:tpl_id>', methods=['GET', 'POST'])
@login_required
def admin_template_edit(tpl_id):
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    tpl = ScoringTemplate.query.get_or_404(tpl_id)
    # 将 dimensions 查询对象转换为列表，以便在模板中使用 sort 过滤器
    dimensions_list = tpl.dimensions.all()
    
    # 检查模板是否被启用的活动使用
    active_events_using = ReviewEvent.query.filter_by(template_id=tpl_id, is_active=True).count()
    can_edit = active_events_using == 0
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        
        # 如果模板被启用的活动使用，不允许更新
        if action == 'batch_update' and not can_edit:
            flash(f'该模板正在被 {active_events_using} 个启用的活动使用，无法修改。请先停用相关活动后再修改模板。', 'error')
            return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)
        
        if action == 'batch_update':
            # 批量更新维度
            dim_ids = request.form.getlist('dim_ids')
            dim_names = request.form.getlist('dim_names')
            dim_descs = request.form.getlist('dim_descs')
            dim_weights = request.form.getlist('dim_weights')
            
            # 验证权重总和
            total_weight = sum(float(w) for w in dim_weights if w)
            if abs(total_weight - 1.0) > 0.01:
                flash(f'权重总和必须等于1.00，当前总和为：{total_weight:.2f}', 'error')
                dimensions_list = tpl.dimensions.all()
                active_events_using = ReviewEvent.query.filter_by(template_id=tpl_id, is_active=True).count()
                can_edit = active_events_using == 0
                return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)
            
            # 验证数据长度一致
            if not (len(dim_ids) == len(dim_names) == len(dim_descs) == len(dim_weights)):
                flash('数据格式错误', 'error')
                dimensions_list = tpl.dimensions.all()
                active_events_using = ReviewEvent.query.filter_by(template_id=tpl_id, is_active=True).count()
                can_edit = active_events_using == 0
                return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)
            
            # 获取所有现有维度的ID
            existing_dim_ids = {d.id for d in dimensions_list}
            submitted_dim_ids = {int(did) for did in dim_ids if did != 'new'}
            
            # 删除未提交的维度
            dims_to_delete = existing_dim_ids - submitted_dim_ids
            for dim_id in dims_to_delete:
                dim = TemplateDimension.query.get(dim_id)
                if dim and dim.template_id == tpl.id:
                    db.session.delete(dim)
            
            # 更新或创建维度
            for i, dim_id in enumerate(dim_ids):
                dim_name = dim_names[i].strip()
                dim_desc = dim_descs[i].strip()
                try:
                    dim_weight = float(dim_weights[i])
                except (ValueError, IndexError):
                    flash(f'第{i+1}个维度的权重无效', 'error')
                    dimensions_list = tpl.dimensions.all()
                    active_events_using = ReviewEvent.query.filter_by(template_id=tpl_id, is_active=True).count()
                    can_edit = active_events_using == 0
                    return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)
                
                if not dim_name:
                    flash(f'第{i+1}个维度的名称不能为空', 'error')
                    dimensions_list = tpl.dimensions.all()
                    active_events_using = ReviewEvent.query.filter_by(template_id=tpl_id, is_active=True).count()
                    can_edit = active_events_using == 0
                    return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)
                
                if dim_id == 'new':
                    # 创建新维度
                    dim = TemplateDimension(
                        template_id=tpl.id,
                        name=dim_name,
                        description=dim_desc,
                        weight=dim_weight,
                        order_index=i
                    )
                    db.session.add(dim)
                else:
                    # 更新现有维度
                    try:
                        dim_id_int = int(dim_id)
                        dim = TemplateDimension.query.get(dim_id_int)
                        if dim and dim.template_id == tpl.id:
                            dim.name = dim_name
                            dim.description = dim_desc
                            dim.weight = dim_weight
                            dim.order_index = i
                        else:
                            flash(f'维度ID {dim_id} 不存在或不属于此模板', 'error')
                            dimensions_list = tpl.dimensions.all()
                            active_events_using = ReviewEvent.query.filter_by(template_id=tpl_id, is_active=True).count()
                            can_edit = active_events_using == 0
                            return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)
                    except ValueError:
                        flash(f'无效的维度ID: {dim_id}', 'error')
                        dimensions_list = tpl.dimensions.all()
                        active_events_using = ReviewEvent.query.filter_by(template_id=tpl_id, is_active=True).count()
                        can_edit = active_events_using == 0
                        return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)
            
            try:
                db.session.commit()
                flash('维度已保存', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'保存失败：{str(e)}', 'error')
            
            return redirect(url_for('admin_template_edit', tpl_id=tpl.id))
        else:
            # 旧的单个添加维度方式（保留兼容性）
            dim_name = request.form.get('dim_name', '').strip()
            dim_desc = request.form.get('dim_desc', '').strip()
            weight = request.form.get('weight', '1').strip()
            order_index = request.form.get('order_index', '0').strip()
            try:
                weight_f = float(weight)
                order_i = int(order_index)
            except ValueError:
                flash('权重或排序无效', 'error')
                dimensions_list = tpl.dimensions.all()
                active_events_using = ReviewEvent.query.filter_by(template_id=tpl_id, is_active=True).count()
                can_edit = active_events_using == 0
                return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)
            if not dim_name:
                flash('维度名称不能为空', 'error')
            else:
                dim = TemplateDimension(template_id=tpl.id, name=dim_name, description=dim_desc,
                                        weight=weight_f, order_index=order_i)
                db.session.add(dim)
                db.session.commit()
                flash('维度已添加', 'success')
                return redirect(url_for('admin_template_edit', tpl_id=tpl.id))
    return render_template('admin_template_edit.html', template=tpl, dimensions_list=dimensions_list, back_url=url_for('admin_templates'), can_edit=can_edit, active_events_count=active_events_using)

@app.route('/admin/templates/<int:tpl_id>/delete', methods=['POST'])
@login_required
def admin_template_delete(tpl_id):
    """删除评分模板"""
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    template = ScoringTemplate.query.get_or_404(tpl_id)
    
    # 检查是否有活动使用该模板
    events_using = ReviewEvent.query.filter_by(template_id=tpl_id).count()
    if events_using > 0:
        flash(f'无法删除模板：有 {events_using} 个评审活动正在使用此模板，请先修改或删除这些活动', 'error')
        return redirect(url_for('admin_templates'))
    
    # 检查是否有文档使用该模板
    docs_using = Document.query.filter_by(template_id=tpl_id).count()
    if docs_using > 0:
        flash(f'无法删除模板：有 {docs_using} 个文档正在使用此模板，请先处理这些文档', 'error')
        return redirect(url_for('admin_templates'))
    
    # 检查是否在全局设置中被使用
    settings_using = Setting.query.filter_by(active_template_id=tpl_id).count()
    if settings_using > 0:
        flash('无法删除模板：此模板正在全局设置中被使用，请先修改全局设置', 'error')
        return redirect(url_for('admin_templates'))
    
    # 删除模板及其所有维度（级联删除）
    template_name = template.name
    db.session.delete(template)
    db.session.commit()
    
    flash(f'模板 "{template_name}" 已删除', 'success')
    return redirect(url_for('admin_templates'))

@app.route('/api/template/<int:template_id>/dimensions')
@login_required
def api_template_dimensions(template_id):
    """获取模板的维度信息（API）"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403
    
    template = ScoringTemplate.query.get_or_404(template_id)
    dimensions = template.dimensions.all()
    
    return jsonify({
        'success': True,
        'dimensions': [{
            'id': dim.id,
            'name': dim.name,
            'description': dim.description,
            'weight': dim.weight,
            'order_index': dim.order_index
        } for dim in dimensions]
    })

@app.route('/admin/results')
@login_required
def admin_results():
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    # 列出所有教师上传文档及评分明细
    documents = Document.query.order_by(Document.created_at.desc()).all()
    return render_template('admin_results.html', documents=documents, back_url=url_for('dashboard'))

@app.route('/admin/reviewers', methods=['GET', 'POST'])
@login_required
def admin_reviewers():
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    # 批量导入
    if request.method == 'POST' and 'csv' in request.files:
        f = request.files['csv']
        if f and f.filename.lower().endswith('.csv'):
            # 读取简单CSV: username,email,password
            content = f.read().decode('utf-8', errors='ignore').strip().splitlines()
            created = 0
            for line in content:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 3:
                    continue
                username, email, password = parts[:3]
                if not username or not email or not password:
                    continue
                if User.query.filter((User.username==username)|(User.email==email)).first():
                    continue
                u = User(username=username, email=email, role='reviewer', is_active=True)
                u.set_password(password)
                db.session.add(u)
                created += 1
            db.session.commit()
            flash(f'成功导入 {created} 个评审员', 'success')
            return redirect(url_for('admin_reviewers'))
        else:
            flash('请上传CSV文件', 'error')
    reviewers = User.query.filter_by(role='reviewer').order_by(User.created_at.desc()).all()
    teachers = User.query.filter_by(role='teacher').order_by(User.username.asc()).all()
    mappings = ReviewerTeacher.query.all()
    return render_template('admin_reviewers.html', reviewers=reviewers, teachers=teachers, mappings=mappings, back_url=url_for('dashboard'))

@app.route('/admin/reviewers/<int:user_id>/<action>', methods=['POST'])
@login_required
def admin_reviewer_action(user_id, action):
    if not current_user.is_admin():
        return jsonify({'success': False, 'message':'权限不足'}), 403
    u = User.query.get_or_404(user_id)
    if u.role != 'reviewer':
        return jsonify({'success': False, 'message':'仅可操作评审员'}), 400
    if action == 'enable':
        u.is_active = True
    elif action == 'disable':
        u.is_active = False
    elif action == 'delete':
        db.session.delete(u)
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message':'未知操作'}), 400
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/reviewer_map', methods=['POST'])
@login_required
def admin_reviewer_map():
    if not current_user.is_admin():
        return jsonify({'success': False, 'message':'权限不足'}), 403
    reviewer_id = request.form.get('reviewer_id')
    teacher_id = request.form.get('teacher_id')
    if not reviewer_id or not teacher_id:
        return jsonify({'success': False, 'message':'缺少参数'}), 400
    reviewer = User.query.get_or_404(int(reviewer_id))
    teacher = User.query.get_or_404(int(teacher_id))
    if reviewer.role != 'reviewer' or teacher.role != 'teacher':
        return jsonify({'success': False, 'message':'角色不匹配'}), 400
    # 创建映射（若不存在）
    existing = ReviewerTeacher.query.filter_by(reviewer_id=reviewer.id, teacher_id=teacher.id).first()
    if not existing:
        m = ReviewerTeacher(reviewer_id=reviewer.id, teacher_id=teacher.id)
        db.session.add(m)
        db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/reviewer_map/<int:map_id>/delete', methods=['POST'])
@login_required
def admin_reviewer_map_delete(map_id):
    if not current_user.is_admin():
        return jsonify({'success': False, 'message':'权限不足'}), 403
    m = ReviewerTeacher.query.get_or_404(map_id)
    db.session.delete(m)
    db.session.commit()
    return jsonify({'success': True})
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
        # 检查是否需要迁移
        try:
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            missing_columns = []
            
            # 检查 documents 表
            if 'documents' in inspector.get_table_names():
                columns = [col['name'] for col in inspector.get_columns('documents')]
                if 'event_id' not in columns:
                    missing_columns.append('documents.event_id')
                if 'template_id' not in columns:
                    missing_columns.append('documents.template_id')
            
            # 检查 review_events 表
            if 'review_events' in inspector.get_table_names():
                columns = [col['name'] for col in inspector.get_columns('review_events')]
                if 'template_id' not in columns:
                    missing_columns.append('review_events.template_id')
                if 'upload_deadline' not in columns:
                    missing_columns.append('review_events.upload_deadline')
            
            # 检查 users 表
            if 'users' in inspector.get_table_names():
                columns = [col['name'] for col in inspector.get_columns('users')]
                if 'phone' not in columns:
                    missing_columns.append('users.phone')
            
            if missing_columns:
                print("=" * 60)
                print("检测到数据库结构需要更新，正在自动添加缺失字段...")
                print("缺失的字段：")
                for col in missing_columns:
                    print(f"  - {col}")
                
                # 自动添加缺失字段
                try:
                    conn = db.engine.connect()
                    for col in missing_columns:
                        table_name, column_name = col.split('.')
                        if column_name == 'phone':
                            # 添加 phone 字段
                            conn.execute(db.text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(20)"))
                            print(f"✓ 已添加字段: {col}")
                        elif column_name == 'upload_deadline':
                            # 添加 upload_deadline 字段
                            conn.execute(db.text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} DATETIME"))
                            print(f"✓ 已添加字段: {col}")
                        elif column_name == 'template_id':
                            # 添加 template_id 字段（外键）
                            conn.execute(db.text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER"))
                            print(f"✓ 已添加字段: {col}")
                        elif column_name == 'event_id':
                            # 添加 event_id 字段（外键）
                            conn.execute(db.text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER"))
                            print(f"✓ 已添加字段: {col}")
                    conn.commit()
                    conn.close()
                    print("数据库结构更新完成！")
                except Exception as e:
                    print(f"自动添加字段时出错: {e}")
                    print("\n请选择以下方式之一：")
                    print("1. 删除 database.db 文件后重新运行应用（会丢失所有数据）")
                    print("2. 手动使用SQL添加缺失字段")
                print("=" * 60)
        except Exception as e:
            print(f"数据库检查时出错: {e}")
        
        # 创建所有表（如果字段缺失，SQLite可能无法自动添加，需要手动迁移）
        db.create_all()
        
        # 创建默认管理员账户
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@example.com', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('默认管理员账户已创建: username=admin, password=admin123')
        
        # 确保全局设置存在
        _ = get_settings()
        # 默认创建一个示例评审事件（可选）
        if ReviewEvent.query.count() == 0:
            demo = ReviewEvent(name='示例评审活动', description='这是一个示例评审活动，可在后台管理中修改', is_active=True)
            db.session.add(demo)
            db.session.commit()

# ======== 管理：评审事件 ========
@app.route('/admin/events')
@login_required
def admin_events():
    """评审活动列表页面"""
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    events = ReviewEvent.query.order_by(ReviewEvent.created_at.desc()).all()
    return render_template('admin_events.html', events=events, back_url=url_for('dashboard'))

@app.route('/admin/events/create', methods=['GET', 'POST'])
@login_required
def admin_events_create():
    """创建评审活动页面"""
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        start = request.form.get('start_time', '').strip()
        end = request.form.get('end_time', '').strip()
        upload_deadline = request.form.get('upload_deadline', '').strip()
        # 创建活动时默认启用
        is_active = True
        
        # 获取选择的评分模板ID
        template_id = request.form.get('template_id', type=int)
        
        def parse_dt(s):
            if not s: return None
            try:
                # 解析为北京时间（naive datetime），然后转换为 UTC 存储
                beijing_dt = datetime.strptime(s, '%Y-%m-%dT%H:%M')
                # 将北京时间转换为 UTC 存储
                return beijing_to_utc(beijing_dt)
            except ValueError:
                return None
        
        if not name:
            flash('活动名称不能为空', 'error')
        elif not template_id:
            flash('请选择评分模板', 'error')
        else:
            # 验证模板是否存在
            template = ScoringTemplate.query.get(template_id)
            if not template:
                flash('选择的评分模板不存在', 'error')
            else:
                # 创建活动
                ev = ReviewEvent(
                    name=name,
                    description=description,
                    start_time=parse_dt(start),
                    end_time=parse_dt(end),
                    upload_deadline=parse_dt(upload_deadline),
                    is_active=is_active,
                    template_id=template.id
                )
                db.session.add(ev)
                db.session.commit()
                flash('评审活动已创建', 'success')
                return redirect(url_for('admin_events'))
    
    # 获取所有可用的评分模板
    templates = ScoringTemplate.query.order_by(ScoringTemplate.created_at.desc()).all()
    return render_template('admin_events_create.html', templates=templates, back_url=url_for('admin_events'))

@app.route('/admin/events/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_events_edit(event_id):
    """编辑评审活动页面"""
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    event = ReviewEvent.query.get_or_404(event_id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        start = request.form.get('start_time', '').strip()
        end = request.form.get('end_time', '').strip()
        upload_deadline = request.form.get('upload_deadline', '').strip()
        # 编辑活动时不修改 is_active，保持原值
        
        # 获取评分模板ID（编辑时不能修改，使用隐藏字段传递）
        template_id = request.form.get('template_id', type=int)
        
        def parse_dt(s):
            if not s: return None
            try:
                # 解析为北京时间（naive datetime），然后转换为 UTC 存储
                beijing_dt = datetime.strptime(s, '%Y-%m-%dT%H:%M')
                # 将北京时间转换为 UTC 存储
                return beijing_to_utc(beijing_dt)
            except ValueError:
                return None
        
        if not name:
            flash('活动名称不能为空', 'error')
        elif not template_id or template_id != event.template_id:
            flash('编辑活动时不能更改评分模板', 'error')
        else:
            # 更新活动（不修改模板和启用状态）
            event.name = name
            event.description = description
            event.start_time = parse_dt(start)
            event.end_time = parse_dt(end)
            event.upload_deadline = parse_dt(upload_deadline)
            # 不修改 event.is_active 和 event.template_id
            
            db.session.commit()
            flash('评审活动已更新', 'success')
            return redirect(url_for('admin_events'))
    
    # 将 UTC 时间转换为北京时间用于显示
    start_time_beijing = utc_to_beijing(event.start_time) if event.start_time else None
    end_time_beijing = utc_to_beijing(event.end_time) if event.end_time else None
    upload_deadline_beijing = utc_to_beijing(event.upload_deadline) if event.upload_deadline else None
    
    return render_template('admin_events_edit.html', 
                         event=event, 
                         start_time_beijing=start_time_beijing,
                         end_time_beijing=end_time_beijing,
                         upload_deadline_beijing=upload_deadline_beijing,
                         back_url=url_for('admin_events'))

@app.route('/admin/events/<int:event_id>/toggle_active', methods=['POST'])
@login_required
def admin_event_toggle_active(event_id):
    """切换活动启用/停用状态"""
    if not current_user.is_admin():
        flash('只有管理员可以修改活动状态', 'error')
        return redirect(url_for('dashboard'))
    
    event = ReviewEvent.query.get_or_404(event_id)
    
    event.is_active = not event.is_active
    db.session.commit()
    
    status = '启用' if event.is_active else '停用'
    flash(f'活动 "{event.name}" 已{status}', 'success')
    return redirect(url_for('admin_events'))

@app.route('/admin/events/<int:event_id>/delete', methods=['POST'])
@login_required
def admin_event_delete(event_id):
    if not current_user.is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403
    ev = ReviewEvent.query.get_or_404(event_id)
    confirm_name = request.form.get('confirm_name', '').strip()
    confirm_phrase = request.form.get('confirm_phrase', '').strip()
    # 二次确认：需输入活动名称和固定确认短语
    if confirm_name != ev.name or confirm_phrase != 'DELETE':
        return jsonify({'success': False, 'message': '确认信息不正确'}), 400
    # 级联删除：该活动所有文档与对应评审
    docs = Document.query.filter_by(event_id=ev.id).all()
    for doc in docs:
        # 删除文件
        try:
            if os.path.exists(doc.filepath):
                os.remove(doc.filepath)
        except Exception:
            pass
        # 删除评审
        for r in doc.reviews:
            ReviewDetail.query.filter_by(review_id=r.id).delete()
            db.session.delete(r)
        db.session.delete(doc)
    db.session.delete(ev)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/events/<int:event_id>/visibility', methods=['GET', 'POST'])
@login_required
def admin_event_visibility(event_id):
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    ev = ReviewEvent.query.get_or_404(event_id)
    
    # 获取已选中的用户ID
    selected_teacher_ids = set(m.teacher_id for m in EventTeacher.query.filter_by(event_id=ev.id).all())
    selected_reviewer_ids = set(m.reviewer_id for m in EventReviewer.query.filter_by(event_id=ev.id).all())
    selected_user_ids = selected_teacher_ids | selected_reviewer_ids
    
    if request.method == 'POST':
        # 获取操作类型
        action = request.form.get('action', '')
        
        if action == 'batch_update':
            # 批量更新可见性
            user_ids = request.form.getlist('user_ids')
            visibility = request.form.get('visibility', 'visible')  # visible 或 invisible
            
            # 清空旧数据
            EventTeacher.query.filter_by(event_id=ev.id).delete()
            EventReviewer.query.filter_by(event_id=ev.id).delete()
            
            # 如果设置为可见，则添加选中的用户
            if visibility == 'visible':
                for user_id_str in user_ids:
                    try:
                        user_id = int(user_id_str)
                        user = User.query.get(user_id)
                        if user and user.role in ['teacher', 'reviewer']:
                            if user.role == 'teacher':
                                db.session.add(EventTeacher(event_id=ev.id, teacher_id=user_id))
                            else:
                                db.session.add(EventReviewer(event_id=ev.id, reviewer_id=user_id))
                    except ValueError:
                        continue
            
            db.session.commit()
            # 不显示提示消息
            return redirect(url_for('admin_event_visibility', event_id=ev.id, search=request.args.get('search', ''), filter_role=request.args.get('filter_role', ''), page=request.args.get('page', 1)))
        else:
            # 单个用户切换可见性
            user_id = request.form.get('user_id', type=int)
            if user_id:
                user = User.query.get(user_id)
                if user and user.role in ['teacher', 'reviewer']:
                    is_visible = user_id in selected_user_ids
                    if is_visible:
                        # 移除可见性
                        if user.role == 'teacher':
                            EventTeacher.query.filter_by(event_id=ev.id, teacher_id=user_id).delete()
                        else:
                            EventReviewer.query.filter_by(event_id=ev.id, reviewer_id=user_id).delete()
                    else:
                        # 添加可见性
                        if user.role == 'teacher':
                            db.session.add(EventTeacher(event_id=ev.id, teacher_id=user_id))
                        else:
                            db.session.add(EventReviewer(event_id=ev.id, reviewer_id=user_id))
                    db.session.commit()
                    # 不显示提示消息
            return redirect(url_for('admin_event_visibility', event_id=ev.id, search=request.args.get('search', ''), filter_role=request.args.get('filter_role', ''), page=request.args.get('page', 1)))
    
    # GET 请求：列出所有教师与评审员
    search = request.args.get('search', '').strip()
    filter_role = request.args.get('filter_role', '')  # teacher 或 reviewer
    page = request.args.get('page', 1, type=int)
    per_page = 20  # 每页20条
    
    # 查询所有教师和评审员
    query = User.query.filter(User.role.in_(['teacher', 'reviewer']))
    
    # 名称模糊筛选
    if search:
        query = query.filter(User.username.like(f'%{search}%'))
    
    # 角色筛选
    if filter_role in ['teacher', 'reviewer']:
        query = query.filter(User.role == filter_role)
    
    # 分页
    pagination = query.order_by(User.role.asc(), User.username.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    users = pagination.items
    
    # 更新已选中的用户ID集合
    selected_teacher_ids = set(m.teacher_id for m in EventTeacher.query.filter_by(event_id=ev.id).all())
    selected_reviewer_ids = set(m.reviewer_id for m in EventReviewer.query.filter_by(event_id=ev.id).all())
    selected_user_ids = selected_teacher_ids | selected_reviewer_ids
    
    return render_template('admin_event_visibility.html',
                           event=ev,
                           users=users,
                           selected_user_ids=selected_user_ids,
                           search=search,
                           filter_role=filter_role,
                           pagination=pagination,
                           back_url=url_for('admin_events'))

@app.route('/admin/events/<int:event_id>/documents')
@login_required
def admin_event_documents(event_id):
    """管理员查看活动下的所有文档列表"""
    if not current_user.is_admin():
        flash('只有管理员可以访问此页面', 'error')
        return redirect(url_for('dashboard'))
    
    event = ReviewEvent.query.get_or_404(event_id)
    documents = Document.query.filter_by(event_id=event_id).order_by(Document.created_at.desc()).all()
    
    # 获取活动关联的模板维度（统一使用活动的模板）
    dimensions = []
    if event.template:
        # dimensions 关系已设置为 lazy='dynamic'，可以直接调用 all()
        dimensions = event.template.dimensions.all()
    
    # 为每个文档准备维度平均分数据
    documents_data = []
    total_scores = []  # 用于统计总分
    reviewed_count = 0  # 已评审文件数
    
    for doc in documents:
        dim_averages = doc.get_dimension_averages()
        
        # 构建维度平均分列表（使用活动的模板维度）
        dim_scores = []
        for dim in dimensions:
            avg_score = dim_averages.get(dim.id, None)
            dim_scores.append({
                'name': dim.name,
                'average': avg_score
            })
        
        # 检查是否有评审记录
        has_reviews = doc.get_review_count() > 0
        if has_reviews:
            reviewed_count += 1
        
        # 获取文档的平均总分
        avg_score = doc.get_average_score()
        if avg_score is not None:
            total_scores.append(avg_score)
        
        documents_data.append({
            'document': doc,
            'dimension_scores': dim_scores,
            'has_reviews': has_reviews
        })
    
    # 计算统计指标
    total_files = len(documents)
    avg_total_score = round(sum(total_scores) / len(total_scores), 2) if total_scores else None
    max_total_score = max(total_scores) if total_scores else None
    min_total_score = min(total_scores) if total_scores else None
    
    stats = {
        'total_files': total_files,
        'reviewed_files': reviewed_count,
        'avg_total_score': avg_total_score,
        'max_total_score': max_total_score,
        'min_total_score': min_total_score
    }
    
    from_param = request.args.get('from', '')
    return render_template('admin_event_documents.html',
                         event=event,
                         documents_data=documents_data,
                         stats=stats,
                         back_url=url_for('dashboard'),
                         from_param=from_param)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)

