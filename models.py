from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """用户模型"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)  # 改为可空，因为可能未填写
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='reviewer')  # admin, reviewer, teacher
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    # 新增字段
    phone = db.Column(db.String(20), nullable=True)  # 手机号
    
    # 关系
    reviews = db.relationship('Review', backref='reviewer', lazy='dynamic')
    # 评审员与教师映射（作为评审员查看被分配教师）
    assigned_teachers = db.relationship('ReviewerTeacher', foreign_keys='ReviewerTeacher.reviewer_id',
                                        backref='reviewer_user', lazy='dynamic', cascade='all, delete-orphan')
    # 教师被分配的评审员
    assigned_reviewers = db.relationship('ReviewerTeacher', foreign_keys='ReviewerTeacher.teacher_id',
                                         backref='teacher_user', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def is_admin(self):
        return self.role == 'admin'
    
    def is_teacher(self):
        return self.role == 'teacher'
    
    def __repr__(self):
        return f'<User {self.username}>'

class Document(db.Model):
    """文档模型"""
    __tablename__ = 'documents'
    
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('review_events.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(500), nullable=False)
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploader = db.relationship('User', foreign_keys=[uploader_id], backref='uploaded_documents')
    status = db.Column(db.String(20), default='pending')  # pending, reviewing, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # 评分模板
    template_id = db.Column(db.Integer, db.ForeignKey('scoring_templates.id'), nullable=True)
    template = db.relationship('ScoringTemplate', backref='documents')
    # 评审事件
    event = db.relationship('ReviewEvent', backref='documents')
    
    # 关系
    reviews = db.relationship('Review', backref='document', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Document {self.title}>'
    
    def get_average_score(self):
        """获取平均分"""
        reviews = self.reviews.filter_by(status='completed').all()
        if not reviews:
            return None
        total = sum(r.score for r in reviews)
        return round(total / len(reviews), 2)
    
    def get_review_count(self):
        """获取已完成评审数量"""
        return self.reviews.filter_by(status='completed').count()
    
    def get_dimension_averages(self):
        """获取各个维度的平均分，返回字典 {dimension_id: average_score}"""
        completed_reviews = self.reviews.filter_by(status='completed').all()
        if not completed_reviews:
            return {}
        
        # 收集所有维度的评分
        dimension_scores = {}  # {dimension_id: [scores]}
        for review in completed_reviews:
            for detail in review.details:
                dim_id = detail.dimension_id
                if dim_id not in dimension_scores:
                    dimension_scores[dim_id] = []
                dimension_scores[dim_id].append(detail.score)
        
        # 计算每个维度的平均分
        dimension_averages = {}
        for dim_id, scores in dimension_scores.items():
            if scores:
                dimension_averages[dim_id] = round(sum(scores) / len(scores), 2)
        
        return dimension_averages

class Review(db.Model):
    """评审模型"""
    __tablename__ = 'reviews'
    
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    score = db.Column(db.Float)  # 总分（由多维度加权汇总）
    comment = db.Column(db.Text)  # 评审意见（总体评语）
    status = db.Column(db.String(20), default='pending')  # pending, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 唯一约束：每个文档每个评审者只能评审一次
    __table_args__ = (db.UniqueConstraint('document_id', 'reviewer_id', name='unique_review'),)
    
    def __repr__(self):
        return f'<Review {self.id} for Document {self.document_id}>'


class Announcement(db.Model):
    """平台公告"""
    __tablename__ = 'announcements'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Instruction(db.Model):
    """平台使用说明（可作为单条记录管理）"""
    __tablename__ = 'instructions'
    
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Setting(db.Model):
    """全局设置（单例）"""
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    review_start = db.Column(db.DateTime, nullable=True)
    review_end = db.Column(db.DateTime, nullable=True)
    show_teacher_name = db.Column(db.Boolean, default=True)  # 评审是否看到教师姓名
    active_template_id = db.Column(db.Integer, db.ForeignKey('scoring_templates.id'), nullable=True)
    active_template = db.relationship('ScoringTemplate', foreign_keys=[active_template_id])


class ScoringTemplate(db.Model):
    """评分模板"""
    __tablename__ = 'scoring_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TemplateDimension(db.Model):
    """评分模板维度"""
    __tablename__ = 'template_dimensions'
    
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('scoring_templates.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    weight = db.Column(db.Float, default=1.0)  # 权重
    order_index = db.Column(db.Integer, default=0)
    template = db.relationship('ScoringTemplate', backref=db.backref('dimensions', lazy='dynamic', order_by='TemplateDimension.order_index'), foreign_keys=[template_id])


class ReviewDetail(db.Model):
    """评审明细（维度评分与评语）"""
    __tablename__ = 'review_details'
    
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('reviews.id'), nullable=False)
    dimension_id = db.Column(db.Integer, db.ForeignKey('template_dimensions.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    comment = db.Column(db.Text)  # 维度级评语（可选）
    review = db.relationship('Review', backref='details')
    dimension = db.relationship('TemplateDimension')


class ReviewerTeacher(db.Model):
    """评审员与教师的对应关系"""
    __tablename__ = 'reviewer_teachers'
    
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('reviewer_id', 'teacher_id', name='unique_reviewer_teacher'),)


class ReviewEvent(db.Model):
    """评审事件/活动"""
    __tablename__ = 'review_events'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    upload_deadline = db.Column(db.DateTime, nullable=True)  # 上传截止时间
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # 关联评分模板
    template_id = db.Column(db.Integer, db.ForeignKey('scoring_templates.id'), nullable=True)
    template = db.relationship('ScoringTemplate', backref='events', foreign_keys=[template_id])


class EventTeacher(db.Model):
    """活动对教师的可见性白名单；若某活动存在任一教师记录，则仅这些教师可见；若为空则所有教师可见"""
    __tablename__ = 'event_teachers'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('review_events.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('event_id', 'teacher_id', name='unique_event_teacher'),)


class EventReviewer(db.Model):
    """活动对评审员的可见性白名单；若某活动存在任一评审员记录，则仅这些评审员可见；若为空则所有评审员可见"""
    __tablename__ = 'event_reviewers'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('review_events.id'), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('event_id', 'reviewer_id', name='unique_event_reviewer'),)


