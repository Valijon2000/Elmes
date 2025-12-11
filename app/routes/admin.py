from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from app.models import User, Faculty, Group, Subject, TeacherSubject, Announcement, GradeScale, Schedule
from app import db
from functools import wraps
from datetime import datetime

bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    """Faqat admin uchun"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash("Sizda bu sahifaga kirish huquqi yo'q", 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# ==================== ASOSIY SAHIFA ====================
@bp.route('/')
@login_required
@admin_required
def index():
    stats = {
        'total_users': User.query.count(),
        'total_students': User.query.filter_by(role='student').count(),
        'total_teachers': User.query.filter_by(role='teacher').count(),
        'total_deans': User.query.filter_by(role='dean').count(),
        'total_faculties': Faculty.query.count(),
        'total_groups': Group.query.count(),
        'total_subjects': Subject.query.count(),
    }
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    return render_template('admin/index.html', stats=stats, recent_users=recent_users)


# ==================== FOYDALANUVCHILAR ====================
@bp.route('/users')
@login_required
@admin_required
def users():
    page = request.args.get('page', 1, type=int)
    role = request.args.get('role', '')
    search = request.args.get('search', '')
    
    query = User.query
    
    if role:
        query = query.filter_by(role=role)
    
    if search:
        query = query.filter(
            (User.full_name.ilike(f'%{search}%')) |
            (User.email.ilike(f'%{search}%'))
        )
    
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20)
    
    stats = {
        'total': User.query.count(),
        'admins': User.query.filter_by(role='admin').count(),
        'deans': User.query.filter_by(role='dean').count(),
        'teachers': User.query.filter_by(role='teacher').count(),
        'students': User.query.filter_by(role='student').count(),
    }
    
    return render_template('admin/users.html', users=users, stats=stats, current_role=role, search=search)


@bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    faculties = Faculty.query.all()
    groups = Group.query.all()
    
    if request.method == 'POST':
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        password = request.form.get('password')
        role = request.form.get('role', '').strip()
        
        # Role tekshiruvi
        if not role or role not in ['admin', 'teacher', 'student', 'dean', 'accounting']:
            flash("Iltimos, rolni tanlang", 'error')
            return render_template('admin/create_user.html', faculties=faculties, groups=groups)
        
        if User.query.filter_by(email=email).first():
            flash("Bu email allaqachon mavjud", 'error')
            return render_template('admin/create_user.html', faculties=faculties, groups=groups)
        
        user = User(
            email=email,
            full_name=full_name,
            role=role,
            phone=request.form.get('phone')
        )
        
        # Rolga qarab qo'shimcha ma'lumotlar
        if role == 'student':
            student_id = request.form.get('student_id')
            if student_id and User.query.filter_by(student_id=student_id).first():
                flash("Bu talaba ID allaqachon mavjud", 'error')
                return render_template('admin/create_user.html', faculties=faculties, groups=groups)
            user.student_id = student_id
            user.group_id = request.form.get('group_id', type=int)
            user.enrollment_year = request.form.get('enrollment_year', type=int)
        
        elif role == 'teacher':
            user.department = request.form.get('department')
            user.position = request.form.get('position')
        
        elif role == 'dean':
            user.faculty_id = request.form.get('faculty_id', type=int)
            user.position = request.form.get('position', 'Dekan')
        
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash(f"{user.get_role_display()} muvaffaqiyatli yaratildi", 'success')
        return redirect(url_for('admin.users'))
    
    return render_template('admin/create_user.html', faculties=faculties, groups=groups)


@bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    faculties = Faculty.query.all()
    groups = Group.query.all()
    
    if request.method == 'POST':
        user.email = request.form.get('email')
        user.full_name = request.form.get('full_name')
        new_role = request.form.get('role', '').strip()
        
        # Role tekshiruvi
        if not new_role or new_role not in ['admin', 'teacher', 'student', 'dean', 'accounting']:
            flash("Iltimos, rolni tanlang", 'error')
            return render_template('admin/edit_user.html', user=user, faculties=faculties, groups=groups)
        
        user.role = new_role
        user.is_active = request.form.get('is_active') == 'on'
        user.phone = request.form.get('phone')
        
        # Rolga qarab qo'shimcha ma'lumotlar
        if user.role == 'student':
            user.student_id = request.form.get('student_id')
            user.group_id = request.form.get('group_id', type=int)
            user.enrollment_year = request.form.get('enrollment_year', type=int)
        elif user.role == 'teacher':
            user.department = request.form.get('department')
            user.position = request.form.get('position')
        elif user.role == 'dean':
            user.faculty_id = request.form.get('faculty_id', type=int)
            user.position = request.form.get('position')
        
        new_password = request.form.get('new_password')
        if new_password:
            user.set_password(new_password)
        
        db.session.commit()
        flash("Foydalanuvchi muvaffaqiyatli yangilandi", 'success')
        return redirect(url_for('admin.users'))
    
    return render_template('admin/edit_user.html', user=user, faculties=faculties, groups=groups)


@bp.route('/users/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(id):
    user = User.query.get_or_404(id)
    
    if user.id == current_user.id:
        flash("O'zingizni bloklashingiz mumkin emas", 'error')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        status = "faollashtirildi" if user.is_active else "bloklandi"
        flash(f"Foydalanuvchi {status}", 'success')
    
    return redirect(url_for('admin.users'))


@bp.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(id):
    user = User.query.get_or_404(id)
    
    if user.id == current_user.id:
        flash("O'zingizni o'chirishingiz mumkin emas", 'error')
    else:
        db.session.delete(user)
        db.session.commit()
        flash("Foydalanuvchi o'chirildi", 'success')
    
    return redirect(url_for('admin.users'))


# ==================== FAKULTETLAR ====================
@bp.route('/faculties')
@login_required
@admin_required
def faculties():
    faculties = Faculty.query.all()
    return render_template('admin/faculties.html', faculties=faculties)


@bp.route('/faculties/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_faculty():
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code').upper()
        description = request.form.get('description')
        
        if Faculty.query.filter_by(code=code).first():
            flash("Bu kod allaqachon mavjud", 'error')
            return render_template('admin/create_faculty.html')
        
        faculty = Faculty(name=name, code=code, description=description)
        db.session.add(faculty)
        db.session.commit()
        
        flash("Fakultet muvaffaqiyatli yaratildi", 'success')
        return redirect(url_for('admin.faculties'))
    
    return render_template('admin/create_faculty.html')


@bp.route('/faculties/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_faculty(id):
    faculty = Faculty.query.get_or_404(id)
    
    if request.method == 'POST':
        faculty.name = request.form.get('name')
        faculty.code = request.form.get('code').upper()
        faculty.description = request.form.get('description')
        
        db.session.commit()
        flash("Fakultet yangilandi", 'success')
        return redirect(url_for('admin.faculties'))
    
    return render_template('admin/edit_faculty.html', faculty=faculty)


@bp.route('/faculties/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_faculty(id):
    faculty = Faculty.query.get_or_404(id)
    
    if faculty.groups.count() > 0 or faculty.subjects.count() > 0:
        flash("Fakultetda guruhlar yoki fanlar mavjud. Avval ularni o'chiring", 'error')
    else:
        db.session.delete(faculty)
        db.session.commit()
        flash("Fakultet o'chirildi", 'success')
    
    return redirect(url_for('admin.faculties'))


# ==================== FANLAR ====================
@bp.route('/subjects')
@login_required
@admin_required
def subjects():
    faculty_id = request.args.get('faculty', type=int)
    
    query = Subject.query
    if faculty_id:
        query = query.filter_by(faculty_id=faculty_id)
    
    subjects = query.order_by(Subject.code).all()
    faculties = Faculty.query.all()
    
    return render_template('admin/subjects.html', subjects=subjects, faculties=faculties, current_faculty=faculty_id)


@bp.route('/subjects/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_subject():
    faculties = Faculty.query.all()
    
    if request.method == 'POST':
        code = request.form.get('code').upper()
        
        if Subject.query.filter_by(code=code).first():
            flash("Bu fan kodi allaqachon mavjud", 'error')
            return render_template('admin/create_subject.html', faculties=faculties)
        
        subject = Subject(
            name=request.form.get('name'),
            code=code,
            description=request.form.get('description'),
            credits=request.form.get('credits', 3, type=int),
            faculty_id=request.form.get('faculty_id', type=int),
            semester=request.form.get('semester', 1, type=int)
        )
        db.session.add(subject)
        db.session.commit()
        
        flash("Fan muvaffaqiyatli yaratildi", 'success')
        return redirect(url_for('admin.subjects'))
    
    return render_template('admin/create_subject.html', faculties=faculties)


@bp.route('/subjects/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_subject(id):
    subject = Subject.query.get_or_404(id)
    faculties = Faculty.query.all()
    
    if request.method == 'POST':
        subject.name = request.form.get('name')
        subject.code = request.form.get('code').upper()
        subject.description = request.form.get('description')
        subject.credits = request.form.get('credits', 3, type=int)
        subject.faculty_id = request.form.get('faculty_id', type=int)
        subject.semester = request.form.get('semester', 1, type=int)
        
        db.session.commit()
        flash("Fan yangilandi", 'success')
        return redirect(url_for('admin.subjects'))
    
    return render_template('admin/edit_subject.html', subject=subject, faculties=faculties)


@bp.route('/subjects/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_subject(id):
    subject = Subject.query.get_or_404(id)
    db.session.delete(subject)
    db.session.commit()
    flash("Fan o'chirildi", 'success')
    return redirect(url_for('admin.subjects'))


# ==================== HISOBOTLAR ====================
@bp.route('/reports')
@login_required
@admin_required
def reports():
    from sqlalchemy import func
    
    stats = {
        'total_users': User.query.count(),
        'total_students': User.query.filter_by(role='student').count(),
        'total_teachers': User.query.filter_by(role='teacher').count(),
        'total_faculties': Faculty.query.count(),
        'total_groups': Group.query.count(),
        'total_subjects': Subject.query.count(),
        'active_users': User.query.filter_by(is_active=True).count(),
    }
    
    # Fakultetlar bo'yicha statistika
    faculty_stats = []
    for faculty in Faculty.query.all():
        faculty_stats.append({
            'faculty': faculty,
            'groups': faculty.groups.count(),
            'subjects': faculty.subjects.count(),
            'students': User.query.join(Group).filter(Group.faculty_id == faculty.id).count()
        })
    
    # Guruhlar bo'yicha talabalar
    groups = db.session.query(
        Group.name,
        func.count(User.id)
    ).outerjoin(User, User.group_id == Group.id).group_by(Group.id).all()
    
    return render_template('admin/reports.html', stats=stats, faculty_stats=faculty_stats, groups=groups)


# ==================== BAHOLASH TIZIMI ====================
@bp.route('/grade-scale')
@login_required
@admin_required
def grade_scale():
    """Baholash tizimini ko'rish"""
    grades = GradeScale.query.order_by(GradeScale.order).all()
    return render_template('admin/grade_scale.html', grades=grades)


@bp.route('/grade-scale/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_grade():
    """Yangi baho qo'shish"""
    if request.method == 'POST':
        letter = request.form.get('letter').upper()
        
        # Tekshirish: bu harf mavjudmi
        if GradeScale.query.filter_by(letter=letter).first():
            flash("Bu baho harfi allaqachon mavjud", 'error')
            return render_template('admin/create_grade.html')
        
        # Ball oralig'ini tekshirish
        min_score = request.form.get('min_score', type=int)
        max_score = request.form.get('max_score', type=int)
        
        if min_score > max_score:
            flash("Minimal ball maksimaldan katta bo'lishi mumkin emas", 'error')
            return render_template('admin/create_grade.html')
        
        grade = GradeScale(
            letter=letter,
            name=request.form.get('name'),
            min_score=min_score,
            max_score=max_score,
            description=request.form.get('description'),
            gpa_value=request.form.get('gpa_value', type=float) or 0,
            color=request.form.get('color', 'gray'),
            is_passing=request.form.get('is_passing') == 'on',
            order=request.form.get('order', type=int) or GradeScale.query.count() + 1
        )
        db.session.add(grade)
        db.session.commit()
        
        flash("Baho muvaffaqiyatli qo'shildi", 'success')
        return redirect(url_for('admin.grade_scale'))
    
    return render_template('admin/create_grade.html')


@bp.route('/grade-scale/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_grade(id):
    """Bahoni tahrirlash"""
    grade = GradeScale.query.get_or_404(id)
    
    if request.method == 'POST':
        grade.letter = request.form.get('letter').upper()
        grade.name = request.form.get('name')
        grade.min_score = request.form.get('min_score', type=int)
        grade.max_score = request.form.get('max_score', type=int)
        grade.description = request.form.get('description')
        grade.gpa_value = request.form.get('gpa_value', type=float) or 0
        grade.color = request.form.get('color', 'gray')
        grade.is_passing = request.form.get('is_passing') == 'on'
        grade.order = request.form.get('order', type=int)
        
        db.session.commit()
        flash("Baho yangilandi", 'success')
        return redirect(url_for('admin.grade_scale'))
    
    return render_template('admin/edit_grade.html', grade=grade)


@bp.route('/grade-scale/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_grade(id):
    """Bahoni o'chirish"""
    grade = GradeScale.query.get_or_404(id)
    db.session.delete(grade)
    db.session.commit()
    flash("Baho o'chirildi", 'success')
    return redirect(url_for('admin.grade_scale'))


@bp.route('/grade-scale/reset', methods=['POST'])
@login_required
@admin_required
def reset_grade_scale():
    """Standart baholarni tiklash"""
    # Barcha baholarni o'chirish
    GradeScale.query.delete()
    db.session.commit()
    
    # Standart baholarni qayta yaratish
    GradeScale.init_default_grades()
    
    flash("Baholash tizimi standart holatga qaytarildi", 'success')
    return redirect(url_for('admin.grade_scale'))


# ==================== EXCEL IMPORT ====================
@bp.route('/import/students', methods=['GET', 'POST'])
@login_required
@admin_required
def import_students():
    """Excel fayldan talabalar import qilish"""
    faculties = Faculty.query.all()
    
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash("Fayl tanlanmagan", 'error')
            return redirect(url_for('admin.users', role='student'))
        
        file = request.files['excel_file']
        if file.filename == '':
            flash("Fayl tanlanmagan", 'error')
            return redirect(url_for('admin.users', role='student'))
        
        if not file.filename.endswith(('.xlsx', '.xls')):
            flash("Faqat Excel fayllar (.xlsx, .xls) qo'llab-quvvatlanadi", 'error')
            return redirect(url_for('admin.users', role='student'))
        
        faculty_id = request.form.get('faculty_id', type=int)
        
        try:
            from app.utils.excel_import import import_students_from_excel
            
            result = import_students_from_excel(file, faculty_id=faculty_id)
            
            if result['success']:
                if result['imported'] > 0:
                    flash(f"{result['imported']} ta talaba muvaffaqiyatli import qilindi", 'success')
                else:
                    flash("Hech qanday talaba import qilinmadi", 'warning')
                
                if result['errors']:
                    error_msg = f"Xatolar ({len(result['errors'])}): " + "; ".join(result['errors'][:5])
                    if len(result['errors']) > 5:
                        error_msg += f" va yana {len(result['errors']) - 5} ta xato"
                    flash(error_msg, 'warning')
            else:
                flash(f"Import xatosi: {result['errors'][0] if result['errors'] else 'Noma\'lum xatolik'}", 'error')
                
        except ImportError as e:
            flash(f"Excel import funksiyasi ishlamayapti: {str(e)}", 'error')
        except Exception as e:
            flash(f"Import xatosi: {str(e)}", 'error')
        
        return redirect(url_for('admin.users', role='student'))
    
    return render_template('admin/import_students.html', faculties=faculties)


# ==================== EXCEL EXPORT ====================
@bp.route('/export/students')
@login_required
@admin_required
def export_students():
    """Talabalar ro'yxatini Excel formatida yuklab olish"""
    try:
        from app.utils.excel_export import create_students_excel
    except ImportError:
        flash("Excel export funksiyasi ishlamayapti. Iltimos, 'pip install openpyxl' buyrug'ini bajaring.", 'error')
        return redirect(url_for('admin.users'))
    
    faculty_id = request.args.get('faculty_id', type=int)
    
    if faculty_id:
        faculty = Faculty.query.get_or_404(faculty_id)
        group_ids = [g.id for g in faculty.groups.all()]
        students = User.query.filter(
            User.role == 'student',
            User.group_id.in_(group_ids)
        ).order_by(User.full_name).all()
        faculty_name = faculty.name
    else:
        students = User.query.filter_by(role='student').order_by(User.full_name).all()
        faculty_name = None
    
    excel_file = create_students_excel(students, faculty_name)
    
    filename = f"talabalar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    if faculty_name:
        filename = f"talabalar_{faculty_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return Response(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@bp.route('/export/schedule')
@login_required
@admin_required
def export_schedule():
    """Dars jadvalini Excel formatida yuklab olish"""
    try:
        from app.utils.excel_export import create_schedule_excel
    except ImportError:
        flash("Excel export funksiyasi ishlamayapti. Iltimos, 'pip install openpyxl' buyrug'ini bajaring.", 'error')
        return redirect(url_for('main.schedule'))
    
    group_id = request.args.get('group_id', type=int)
    faculty_id = request.args.get('faculty_id', type=int)
    
    if group_id:
        group = Group.query.get_or_404(group_id)
        schedules = Schedule.query.filter_by(group_id=group_id).order_by(Schedule.day_of_week, Schedule.start_time).all()
        group_name = group.name
        faculty_name = None
    elif faculty_id:
        faculty = Faculty.query.get_or_404(faculty_id)
        group_ids = [g.id for g in faculty.groups.all()]
        schedules = Schedule.query.filter(Schedule.group_id.in_(group_ids)).order_by(Schedule.day_of_week, Schedule.start_time).all()
        group_name = None
        faculty_name = faculty.name
    else:
        schedules = Schedule.query.order_by(Schedule.day_of_week, Schedule.start_time).all()
        group_name = None
        faculty_name = None
    
    excel_file = create_schedule_excel(schedules, group_name, faculty_name)
    
    filename = f"dars_jadvali_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    if group_name:
        filename = f"dars_jadvali_{group_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    elif faculty_name:
        filename = f"dars_jadvali_{faculty_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return Response(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
