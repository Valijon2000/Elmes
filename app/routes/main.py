from flask import Blueprint, render_template, request, redirect, url_for, flash, session, url_for as flask_url_for
from flask_login import login_required, current_user
from app.models import User, Subject, Assignment, Announcement, Schedule, Submission, Message, Group, Faculty, TeacherSubject
from app import db
from datetime import datetime, timedelta
from sqlalchemy import func
from app.utils.translations import get_translation, get_current_language

bp = Blueprint('main', __name__)

@bp.route('/set-language/<lang>')
def set_language(lang):
    """Tilni o'zgartirish"""
    if lang in ['uz', 'ru', 'en']:
        session['language'] = lang
    return redirect(request.referrer or url_for('main.dashboard'))

@bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@bp.route('/dashboard')
@login_required
def dashboard():
    context = {
        'greeting': get_greeting(),
        'today': datetime.now().strftime('%A, %d %B %Y')
    }
    
    if current_user.role == 'admin':
        context.update({
            'total_users': User.query.count(),
            'total_faculties': Faculty.query.count(),
            'total_teachers': User.query.filter_by(role='teacher').count(),
            'total_students': User.query.filter_by(role='student').count(),
            'recent_users': User.query.order_by(User.created_at.desc()).limit(5).all()
        })
    
    elif current_user.role == 'dean':
        faculty = Faculty.query.get(current_user.faculty_id)
        if faculty:
            faculty_group_ids = [g.id for g in faculty.groups.all()]
            context.update({
                'faculty': faculty,
                'total_groups': faculty.groups.count(),
                'total_subjects': faculty.subjects.count(),
                'total_students': User.query.filter(
                    User.role == 'student',
                    User.group_id.in_(faculty_group_ids)
                ).count(),
                'recent_announcements': Announcement.query.order_by(Announcement.created_at.desc()).limit(5).all()
            })
    
    elif current_user.role == 'teacher':
        # O'qituvchiga biriktirilgan fanlar
        teaching = TeacherSubject.query.filter_by(teacher_id=current_user.id).all()
        subjects = list(set([t.subject for t in teaching]))
        groups = list(set([t.group for t in teaching]))
        
        # Baholanmagan topshiriqlar
        pending_count = 0
        for ts in teaching:
            pending_count += Submission.query.join(Assignment).filter(
                Assignment.subject_id == ts.subject_id,
                Assignment.group_id == ts.group_id,
                Submission.score == None
            ).count()
        
        context.update({
            'my_subjects': subjects,
            'my_groups': groups,
            'total_subjects': len(subjects),
            'total_groups': len(groups),
            'pending_submissions': pending_count,
            'today_schedule': get_today_schedule(current_user)
        })
    
    elif current_user.role == 'student':
        # Talabaning guruhi va fanlari
        group = Group.query.get(current_user.group_id) if current_user.group_id else None
        subjects = current_user.get_subjects() if group else []
        
        # To'lov ma'lumotlari
        from app.models import StudentPayment
        payment = StudentPayment.query.filter_by(student_id=current_user.id).first()
        payment_info = None
        if payment:
            payment_info = {
                'contract': float(payment.contract_amount),
                'paid': float(payment.paid_amount),
                'remaining': float(payment.get_remaining_amount()),
                'percentage': payment.get_payment_percentage()
            }
        
        context.update({
            'group': group,
            'my_subjects': subjects,
            'total_subjects': len(subjects),
            'pending_assignments': get_pending_assignments(current_user),
            'recent_grades': get_recent_grades(current_user),
            'today_schedule': get_today_schedule(current_user),
            'payment_info': payment_info
        })
    
    # E'lonlar
    context['announcements'] = Announcement.query.order_by(
        Announcement.is_important.desc(),
        Announcement.created_at.desc()
    ).limit(3).all()
    
    return render_template('dashboard.html', **context)

@bp.route('/schedule')
@login_required
def schedule():
    week_days = ['Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba']
    
    if current_user.role == 'teacher':
        schedules = Schedule.query.filter_by(teacher_id=current_user.id).all()
    elif current_user.role == 'student' and current_user.group_id:
        schedules = Schedule.query.filter_by(group_id=current_user.group_id).all()
    elif current_user.role == 'dean' and current_user.faculty_id:
        faculty = Faculty.query.get(current_user.faculty_id)
        group_ids = [g.id for g in faculty.groups.all()]
        schedules = Schedule.query.filter(Schedule.group_id.in_(group_ids)).all()
    else:
        schedules = Schedule.query.all()
    
    # Hafta kunlariga bo'lish
    schedule_by_day = {i: [] for i in range(6)}
    for s in schedules:
        if s.day_of_week in schedule_by_day:
            schedule_by_day[s.day_of_week].append(s)
    
    # Har bir kun uchun vaqt bo'yicha tartiblash
    for day in schedule_by_day:
        schedule_by_day[day].sort(key=lambda x: x.start_time)
    
    return render_template('schedule.html', 
                         week_days=week_days, 
                         schedule_by_day=schedule_by_day)

@bp.route('/announcements')
@login_required
def announcements():
    page = request.args.get('page', 1, type=int)
    announcements = Announcement.query.order_by(
        Announcement.is_important.desc(),
        Announcement.created_at.desc()
    ).paginate(page=page, per_page=10)
    
    return render_template('announcements.html', announcements=announcements)

@bp.route('/announcements/create', methods=['GET', 'POST'])
@login_required
def create_announcement():
    if not current_user.has_permission('create_announcement'):
        flash("Sizda bu amal uchun ruxsat yo'q", 'error')
        return redirect(url_for('main.announcements'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        is_important = request.form.get('is_important') == 'on'
        target_roles = ','.join(request.form.getlist('target_roles'))
        
        announcement = Announcement(
            title=title,
            content=content,
            is_important=is_important,
            target_roles=target_roles,
            author_id=current_user.id,
            faculty_id=current_user.faculty_id if current_user.role == 'dean' else None
        )
        db.session.add(announcement)
        db.session.commit()
        
        flash("E'lon muvaffaqiyatli yaratildi", 'success')
        return redirect(url_for('main.announcements'))
    
    return render_template('create_announcement.html')

@bp.route('/messages')
@login_required
def messages():
    from app.models import TeacherSubject
    
    # Ruxsatli foydalanuvchilarni aniqlash
    allowed_user_ids = set()
    
    if current_user.role == 'student':
        # Talaba faqat o'ziga biriktirilgan o'qituvchi va dekanga yozishi mumkin
        if current_user.group_id:
            # O'z guruhiga biriktirilgan o'qituvchilar
            teaching_assignments = TeacherSubject.query.filter_by(group_id=current_user.group_id).all()
            teacher_ids = [ta.teacher_id for ta in teaching_assignments]
            allowed_user_ids.update(teacher_ids)
            
            # O'z fakultetidagi dekan
            student_group = Group.query.get(current_user.group_id)
            if student_group and student_group.faculty_id:
                faculty_dean = User.query.filter_by(
                    role='dean',
                    faculty_id=student_group.faculty_id
                ).first()
                if faculty_dean:
                    allowed_user_ids.add(faculty_dean.id)
        
    elif current_user.role == 'dean':
        # Dekan faqat o'z fakultetidagi talabalarga yozishi mumkin
        if current_user.faculty_id:
            faculty_groups = Group.query.filter_by(faculty_id=current_user.faculty_id).all()
            group_ids = [g.id for g in faculty_groups]
            students = User.query.filter(
                User.role == 'student',
                User.group_id.in_(group_ids)
            ).all()
            allowed_user_ids.update([s.id for s in students])
        
    elif current_user.role == 'teacher':
        # O'qituvchi o'z guruhlaridagi talabalarga yozishi mumkin
        teaching_groups = TeacherSubject.query.filter_by(teacher_id=current_user.id).all()
        group_ids = [tg.group_id for tg in teaching_groups]
        students = User.query.filter(
            User.role == 'student',
            User.group_id.in_(group_ids)
        ).all()
        allowed_user_ids.update([s.id for s in students])
        
        # O'qituvchilar o'rtasida ham yozish mumkin
        teachers = User.query.filter_by(role='teacher').filter(User.id != current_user.id).all()
        allowed_user_ids.update([t.id for t in teachers])
        
        # Dekanlarga ham yozish mumkin
        deans = User.query.filter_by(role='dean').all()
        allowed_user_ids.update([d.id for d in deans])
        
    else:
        # Admin va boshqalar barcha foydalanuvchilar bilan yozishi mumkin
        all_users = User.query.filter(User.id != current_user.id).all()
        allowed_user_ids.update([u.id for u in all_users])
    
    # Barcha suhbatlar (faqat ruxsatli foydalanuvchilar bilan)
    sent = db.session.query(Message.receiver_id).filter_by(sender_id=current_user.id).filter(Message.receiver_id.in_(allowed_user_ids)).distinct()
    received = db.session.query(Message.sender_id).filter_by(receiver_id=current_user.id).filter(Message.sender_id.in_(allowed_user_ids)).distinct()
    
    user_ids = set([r[0] for r in sent] + [r[0] for r in received])
    chat_users = User.query.filter(User.id.in_(user_ids)).all()
    
    # Har bir foydalanuvchi bilan so'nggi xabar
    chats = []
    for user in chat_users:
        last_message = Message.query.filter(
            ((Message.sender_id == current_user.id) & (Message.receiver_id == user.id)) |
            ((Message.sender_id == user.id) & (Message.receiver_id == current_user.id))
        ).order_by(Message.created_at.desc()).first()
        
        unread_count = Message.query.filter_by(
            sender_id=user.id,
            receiver_id=current_user.id,
            is_read=False
        ).count()
        
        chats.append({
            'user': user,
            'last_message': last_message,
            'unread_count': unread_count
        })
    
    chats.sort(key=lambda x: x['last_message'].created_at if x['last_message'] else datetime.min, reverse=True)
    
    # Ruxsatli foydalanuvchilar ro'yxati (yangi suhbat boshlash uchun)
    available_users = User.query.filter(User.id.in_(allowed_user_ids)).filter(User.id != current_user.id).all()
    
    return render_template('messages.html', chats=chats, available_users=available_users)

@bp.route('/messages/<int:user_id>', methods=['GET', 'POST'])
@login_required
def chat(user_id):
    from app.models import TeacherSubject, Group
    
    other_user = User.query.get_or_404(user_id)
    
    # Ruxsatni tekshirish
    can_message = False
    
    if current_user.role == 'student':
        # Talaba faqat o'ziga biriktirilgan o'qituvchi va dekanga yozishi mumkin
        can_message = False
        
        if current_user.group_id:
            # O'z guruhiga biriktirilgan o'qituvchilarga
            if other_user.role == 'teacher':
                teaching = TeacherSubject.query.filter_by(
                    teacher_id=other_user.id,
                    group_id=current_user.group_id
                ).first()
                can_message = teaching is not None
            
            # O'z fakultetidagi dekanga
            elif other_user.role == 'dean':
                student_group = Group.query.get(current_user.group_id)
                if student_group and student_group.faculty_id:
                    can_message = other_user.faculty_id == student_group.faculty_id
        
    elif current_user.role == 'dean':
        # Dekan faqat o'z fakultetidagi talabalarga yozishi mumkin
        if other_user.role == 'student' and current_user.faculty_id:
            if other_user.group_id:
                group = Group.query.get(other_user.group_id)
                can_message = group and group.faculty_id == current_user.faculty_id
        else:
            can_message = False
            
    elif current_user.role == 'teacher':
        # O'qituvchi o'z guruhlaridagi talabalarga, boshqa o'qituvchilarga va dekanlarga yozishi mumkin
        if other_user.role == 'student':
            if other_user.group_id:
                teaching = TeacherSubject.query.filter_by(
                    teacher_id=current_user.id,
                    group_id=other_user.group_id
                ).first()
                can_message = teaching is not None
        elif other_user.role in ['teacher', 'dean']:
            can_message = True
        else:
            can_message = False
            
    else:
        # Admin va boshqalar barcha foydalanuvchilar bilan yozishi mumkin
        can_message = True
    
    if not can_message:
        flash("Siz bu foydalanuvchiga xabar yubora olmaysiz", 'error')
        return redirect(url_for('main.messages'))
    
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            message = Message(
                sender_id=current_user.id,
                receiver_id=user_id,
                content=content
            )
            db.session.add(message)
            db.session.commit()
    
    # Xabarlarni o'qilgan deb belgilash
    Message.query.filter_by(
        sender_id=user_id,
        receiver_id=current_user.id,
        is_read=False
    ).update({'is_read': True})
    db.session.commit()
    
    # Barcha xabarlar
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.created_at.asc()).all()
    
    return render_template('chat.html', other_user=other_user, messages=messages)

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_user.full_name = request.form.get('full_name', current_user.full_name)
        current_user.phone = request.form.get('phone', current_user.phone)
        
        new_password = request.form.get('new_password')
        if new_password:
            current_password = request.form.get('current_password')
            if current_user.check_password(current_password):
                current_user.set_password(new_password)
                flash("Parol muvaffaqiyatli o'zgartirildi", 'success')
            else:
                flash("Joriy parol noto'g'ri", 'error')
                return render_template('settings.html')
        
        db.session.commit()
        flash("Sozlamalar saqlandi", 'success')
    
    return render_template('settings.html')


# Yordamchi funksiyalar
def get_greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Xayrli tong"
    elif hour < 18:
        return "Xayrli kun"
    return "Xayrli kech"

def get_today_schedule(user):
    today = datetime.now().weekday()
    if today > 5:
        return []
    
    if user.role == 'teacher':
        return Schedule.query.filter(
            Schedule.teacher_id == user.id,
            Schedule.day_of_week == today
        ).order_by(Schedule.start_time).all()
    elif user.role == 'student' and user.group_id:
        return Schedule.query.filter(
            Schedule.group_id == user.group_id,
            Schedule.day_of_week == today
        ).order_by(Schedule.start_time).all()
    return []

def get_pending_assignments(user):
    if not user.group_id:
        return []
    
    assignments = Assignment.query.filter_by(group_id=user.group_id).all()
    pending = []
    for assignment in assignments:
        submission = Submission.query.filter_by(
            student_id=user.id,
            assignment_id=assignment.id
        ).first()
        if not submission:
            pending.append(assignment)
    return pending[:5]

def get_recent_grades(user):
    return Submission.query.filter(
        Submission.student_id == user.id,
        Submission.score != None
    ).order_by(Submission.graded_at.desc()).limit(5).all()
