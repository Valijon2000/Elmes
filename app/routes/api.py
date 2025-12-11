from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.models import User, Subject, Message, Faculty, Group
from app import db

bp = Blueprint('api', __name__, url_prefix='/api')

@bp.route('/users/search')
@login_required
def search_users():
    from app.models import TeacherSubject, Group
    
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    # Ruxsatli foydalanuvchilarni aniqlash
    allowed_user_ids = set()
    
    if current_user.role == 'student':
        # Talaba faqat o'ziga biriktirilgan o'qituvchi va dekanni qidirishi mumkin
        users = []
        
        if current_user.group_id:
            # O'z guruhiga biriktirilgan o'qituvchilar
            teaching_assignments = TeacherSubject.query.filter_by(group_id=current_user.group_id).all()
            teacher_ids = [ta.teacher_id for ta in teaching_assignments]
            
            teachers = User.query.filter(
                User.id.in_(teacher_ids),
                ((User.full_name.ilike(f'%{query}%')) |
                 (User.email.ilike(f'%{query}%')))
            ).all()
            users.extend(teachers)
            
            # O'z fakultetidagi dekan
            from app.models import Group
            student_group = Group.query.get(current_user.group_id)
            if student_group and student_group.faculty_id:
                dean = User.query.filter_by(
                    role='dean',
                    faculty_id=student_group.faculty_id
                ).filter(
                    (User.full_name.ilike(f'%{query}%')) |
                    (User.email.ilike(f'%{query}%'))
                ).first()
                if dean:
                    users.append(dean)
        
    elif current_user.role == 'dean':
        # Dekan faqat o'z fakultetidagi talabalarni qidirishi mumkin
        if current_user.faculty_id:
            faculty_groups = Group.query.filter_by(faculty_id=current_user.faculty_id).all()
            group_ids = [g.id for g in faculty_groups]
            users = User.query.filter(
                User.role == 'student',
                User.group_id.in_(group_ids),
                ((User.full_name.ilike(f'%{query}%')) |
                 (User.email.ilike(f'%{query}%')))
            ).all()
        else:
            users = []
            
    elif current_user.role == 'teacher':
        # O'qituvchi o'z guruhlaridagi talabalarni, boshqa o'qituvchilarni va dekanlarni qidirishi mumkin
        teaching_groups = TeacherSubject.query.filter_by(teacher_id=current_user.id).all()
        group_ids = [tg.group_id for tg in teaching_groups]
        
        students = User.query.filter(
            User.role == 'student',
            User.group_id.in_(group_ids),
            ((User.full_name.ilike(f'%{query}%')) |
             (User.email.ilike(f'%{query}%')))
        ).all()
        
        teachers = User.query.filter(
            User.role == 'teacher',
            User.id != current_user.id,
            ((User.full_name.ilike(f'%{query}%')) |
             (User.email.ilike(f'%{query}%')))
        ).all()
        
        deans = User.query.filter_by(role='dean').filter(
            (User.full_name.ilike(f'%{query}%')) |
            (User.email.ilike(f'%{query}%'))
        ).all()
        
        users = students + teachers + deans
        
    else:
        # Admin va boshqalar barcha foydalanuvchilarni qidirishi mumkin
        users = User.query.filter(
            User.id != current_user.id,
            (User.full_name.ilike(f'%{query}%')) |
            (User.email.ilike(f'%{query}%'))
        ).limit(10).all()
    
    return jsonify([{
        'id': u.id,
        'full_name': u.full_name,
        'email': u.email,
        'role': u.get_role_display()
    } for u in users])

@bp.route('/messages/unread')
@login_required
def unread_messages():
    count = Message.query.filter_by(
        receiver_id=current_user.id,
        is_read=False
    ).count()
    return jsonify({'count': count})

@bp.route('/dashboard/stats')
@login_required
def dashboard_stats():
    if current_user.role == 'admin':
        return jsonify({
            'users': User.query.count(),
            'subjects': Subject.query.count(),
            'faculties': Faculty.query.count(),
            'groups': Group.query.count(),
            'teachers': User.query.filter_by(role='teacher').count(),
            'students': User.query.filter_by(role='student').count()
        })
    return jsonify({})
