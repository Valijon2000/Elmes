from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from app.models import User, StudentPayment, Group, Faculty
from app import db
from functools import wraps
from datetime import datetime
from sqlalchemy import func

bp = Blueprint('accounting', __name__, url_prefix='/accounting')

def accounting_required(f):
    """Faqat buxgalteriya uchun"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'accounting':
            flash("Sizda bu sahifaga kirish huquqi yo'q", 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/')
@login_required
def index():
    """Buxgalteriya asosiy sahifasi"""
    # Talaba faqat o'z ma'lumotlarini ko'radi
    if current_user.role == 'student':
        payments = StudentPayment.query.filter_by(student_id=current_user.id).order_by(StudentPayment.created_at.desc()).all()
        return render_template('accounting/student_payments.html', payments=payments, student=current_user)
    
    # Buxgalteriya, dekan va admin uchun
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    group_id = request.args.get('group', type=int)
    faculty_id = request.args.get('faculty', type=int)
    
    if current_user.role == 'dean':
        # Dekan faqat o'z fakultetidagi talabalarni ko'radi
        faculty = Faculty.query.get(current_user.faculty_id)
        if not faculty:
            flash("Sizga fakultet biriktirilmagan", 'error')
            return redirect(url_for('main.dashboard'))
        
        faculty_group_ids = [g.id for g in faculty.groups.all()]
        student_ids = [s.id for s in User.query.filter(
            User.role == 'student',
            User.group_id.in_(faculty_group_ids)
        ).all()]
        
        query = StudentPayment.query.filter(StudentPayment.student_id.in_(student_ids))
        
        if search:
            query = query.join(User).filter(
                (User.full_name.ilike(f'%{search}%')) |
                (User.student_id.ilike(f'%{search}%'))
            )
        
        if group_id:
            group_student_ids = [s.id for s in User.query.filter_by(role='student', group_id=group_id).all()]
            query = query.filter(StudentPayment.student_id.in_(group_student_ids))
        
        payments = query.order_by(StudentPayment.created_at.desc()).paginate(page=page, per_page=20)
        groups = faculty.groups.order_by(Group.name).all()
        
        # Statistika
        total_contract = db.session.query(func.sum(StudentPayment.contract_amount)).filter(
            StudentPayment.student_id.in_(student_ids)
        ).scalar() or 0
        total_paid = db.session.query(func.sum(StudentPayment.paid_amount)).filter(
            StudentPayment.student_id.in_(student_ids)
        ).scalar() or 0
        
        # Kurs bo'yicha to'lov foizi statistikasi
        from collections import defaultdict
        payment_stats_by_course = defaultdict(lambda: {
            '0%': 0, '25%': 0, '50%': 0, '75%': 0, '100%': 0, 'total': 0
        })
        
        # Fakultet talabalari to'lov ma'lumotlari
        faculty_payments = StudentPayment.query.filter(
            StudentPayment.student_id.in_(student_ids)
        ).join(User).join(Group).all()
        
        for payment in faculty_payments:
            if payment.student and payment.student.group:
                course_year = payment.student.group.course_year
                percentage = payment.get_payment_percentage()
                
                # To'lov foiziga qarab guruhlash
                if percentage == 0:
                    payment_stats_by_course[course_year]['0%'] += 1
                elif 0 < percentage <= 25:
                    payment_stats_by_course[course_year]['0%'] += 1
                elif 25 < percentage <= 50:
                    payment_stats_by_course[course_year]['25%'] += 1
                elif 50 < percentage <= 75:
                    payment_stats_by_course[course_year]['50%'] += 1
                elif 75 < percentage < 100:
                    payment_stats_by_course[course_year]['75%'] += 1
                else:  # 100% va yuqori
                    payment_stats_by_course[course_year]['100%'] += 1
                
                payment_stats_by_course[course_year]['total'] += 1
        
        # Kurs bo'yicha tartiblash
        payment_stats_by_course = dict(sorted(payment_stats_by_course.items()))
        
        return render_template('accounting/index.html', 
                             payments=payments, 
                             faculty=faculty,
                             groups=groups,
                             current_group=group_id,
                             search=search,
                             total_contract=float(total_contract),
                             total_paid=float(total_paid),
                             payment_stats_by_course=payment_stats_by_course)
    
    elif current_user.role == 'accounting':
        # Buxgalteriya barcha ma'lumotlarni ko'radi va boshqaradi
        query = StudentPayment.query
        
        if search:
            query = query.join(User).filter(
                (User.full_name.ilike(f'%{search}%')) |
                (User.student_id.ilike(f'%{search}%'))
            )
        
        if group_id:
            group_student_ids = [s.id for s in User.query.filter_by(role='student', group_id=group_id).all()]
            query = query.filter(StudentPayment.student_id.in_(group_student_ids))
        
        if faculty_id:
            faculty = Faculty.query.get(faculty_id)
            if faculty:
                faculty_group_ids = [g.id for g in faculty.groups.all()]
                faculty_student_ids = [s.id for s in User.query.filter(
                    User.role == 'student',
                    User.group_id.in_(faculty_group_ids)
                ).all()]
                query = query.filter(StudentPayment.student_id.in_(faculty_student_ids))
        
        payments = query.order_by(StudentPayment.created_at.desc()).paginate(page=page, per_page=20)
        groups = Group.query.order_by(Group.name).all()
        faculties = Faculty.query.all()
        
        # Statistika
        total_contract = db.session.query(func.sum(StudentPayment.contract_amount)).scalar() or 0
        total_paid = db.session.query(func.sum(StudentPayment.paid_amount)).scalar() or 0
        
        # Kurs bo'yicha to'lov foizi statistikasi
        from collections import defaultdict
        payment_stats_by_course = defaultdict(lambda: {
            '0%': 0, '25%': 0, '50%': 0, '75%': 0, '100%': 0, 'total': 0
        })
        
        # Barcha to'lov ma'lumotlarini olish
        all_payments = StudentPayment.query.join(User).join(Group).all()
        
        for payment in all_payments:
            if payment.student and payment.student.group:
                course_year = payment.student.group.course_year
                percentage = payment.get_payment_percentage()
                
                # To'lov foiziga qarab guruhlash
                if percentage == 0:
                    payment_stats_by_course[course_year]['0%'] += 1
                elif 0 < percentage <= 25:
                    payment_stats_by_course[course_year]['0%'] += 1
                elif 25 < percentage <= 50:
                    payment_stats_by_course[course_year]['25%'] += 1
                elif 50 < percentage <= 75:
                    payment_stats_by_course[course_year]['50%'] += 1
                elif 75 < percentage < 100:
                    payment_stats_by_course[course_year]['75%'] += 1
                else:  # 100% va yuqori
                    payment_stats_by_course[course_year]['100%'] += 1
                
                payment_stats_by_course[course_year]['total'] += 1
        
        # Kurs bo'yicha tartiblash
        payment_stats_by_course = dict(sorted(payment_stats_by_course.items()))
        
        return render_template('accounting/index.html', 
                             payments=payments, 
                             groups=groups,
                             faculties=faculties,
                             current_group=group_id,
                             current_faculty=faculty_id,
                             search=search,
                             total_contract=float(total_contract),
                             total_paid=float(total_paid),
                             payment_stats_by_course=payment_stats_by_course)
    
    else:
        # Boshqa rollar uchun ruxsat yo'q
        flash("Sizda bu sahifaga kirish huquqi yo'q", 'error')
        return redirect(url_for('main.dashboard'))


@bp.route('/import', methods=['GET', 'POST'])
@login_required
@accounting_required
def import_payments():
    """Excel fayldan to'lov ma'lumotlarini import qilish"""
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash("Fayl tanlanmagan", 'error')
            return redirect(url_for('accounting.import_payments'))
        
        file = request.files['excel_file']
        if file.filename == '':
            flash("Fayl tanlanmagan", 'error')
            return redirect(url_for('accounting.import_payments'))
        
        if not file.filename.endswith(('.xlsx', '.xls')):
            flash("Faqat Excel fayllar (.xlsx, .xls) qo'llab-quvvatlanadi", 'error')
            return redirect(url_for('accounting.import_payments'))
        
        try:
            from app.utils.excel_import import import_payments_from_excel
            
            result = import_payments_from_excel(file)
            
            if result['success']:
                if result['imported'] > 0:
                    flash(f"{result['imported']} ta yozuv muvaffaqiyatli import qilindi", 'success')
                else:
                    flash("Hech qanday yozuv import qilinmadi", 'warning')
                
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
        
        return redirect(url_for('accounting.index'))
    
    return render_template('accounting/import_payments.html')


@bp.route('/import/sample')
@login_required
@accounting_required
def download_sample_contracts():
    """Kontrakt import uchun namuna Excel fayl yuklab olish"""
    try:
        from app.utils.excel_export import create_sample_contracts_excel
    except ImportError:
        flash("Excel export funksiyasi ishlamayapti. Iltimos, 'pip install openpyxl' buyrug'ini bajaring.", 'error')
        return redirect(url_for('accounting.import_payments'))
    
    excel_file = create_sample_contracts_excel()
    filename = f"kontrakt_namuna_{datetime.now().strftime('%Y%m%d')}.xlsx"
    
    return Response(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@bp.route('/student/<int:student_id>')
@login_required
def student_payments(student_id):
    """Talaba to'lov ma'lumotlari"""
    student = User.query.get_or_404(student_id)
    
    # Ruxsat tekshiruvi
    if current_user.role == 'student' and current_user.id != student_id:
        flash("Sizda bu sahifaga kirish huquqi yo'q", 'error')
        return redirect(url_for('main.dashboard'))
    
    if current_user.role == 'dean':
        if not student.group or student.group.faculty_id != current_user.faculty_id:
            flash("Sizda bu sahifaga kirish huquqi yo'q", 'error')
            return redirect(url_for('main.dashboard'))
    
    payments = StudentPayment.query.filter_by(student_id=student_id).order_by(StudentPayment.created_at.desc()).all()
    
    # Statistika hisoblash
    total_contract = 0
    total_paid = 0
    if payments:
        total_contract = float(payments[0].contract_amount)
        total_paid = sum(float(p.paid_amount) for p in payments)
    total_remaining = total_contract - total_paid
    percentage = (total_paid / total_contract * 100) if total_contract > 0 else 0
    
    return render_template('accounting/student_payments.html', 
                         payments=payments, 
                         student=student,
                         total_contract=total_contract,
                         total_paid=total_paid,
                         total_remaining=total_remaining,
                         percentage=percentage)


@bp.route('/export/contracts')
@login_required
def export_contracts():
    """Kontrakt ma'lumotlarini Excel formatida yuklab olish (kurs bo'yicha)"""
    try:
        from app.utils.excel_export import create_contracts_excel
    except ImportError:
        flash("Excel export funksiyasi ishlamayapti. Iltimos, 'pip install openpyxl' buyrug'ini bajaring.", 'error')
        return redirect(url_for('accounting.index'))
    
    course_year = request.args.get('course', type=int)
    group_id = request.args.get('group', type=int)
    faculty_id = request.args.get('faculty', type=int)
    
    query = StudentPayment.query.join(User).join(Group)
    
    # Foydalanuvchi roliga qarab filtrlash
    if current_user.role == 'dean':
        faculty = Faculty.query.get(current_user.faculty_id)
        if not faculty:
            flash("Sizga fakultet biriktirilmagan", 'error')
            return redirect(url_for('main.dashboard'))
        
        faculty_group_ids = [g.id for g in faculty.groups.all()]
        student_ids = [s.id for s in User.query.filter(
            User.role == 'student',
            User.group_id.in_(faculty_group_ids)
        ).all()]
        query = query.filter(StudentPayment.student_id.in_(student_ids))
    
    if group_id:
        group_student_ids = [s.id for s in User.query.filter_by(role='student', group_id=group_id).all()]
        query = query.filter(StudentPayment.student_id.in_(group_student_ids))
    
    if faculty_id:
        faculty = Faculty.query.get(faculty_id)
        if faculty:
            faculty_group_ids = [g.id for g in faculty.groups.all()]
            faculty_student_ids = [s.id for s in User.query.filter(
                User.role == 'student',
                User.group_id.in_(faculty_group_ids)
            ).all()]
            query = query.filter(StudentPayment.student_id.in_(faculty_student_ids))
    
    if course_year:
        query = query.filter(Group.course_year == course_year)
    
    payments = query.all()
    
    if not payments:
        flash("Kontrakt ma'lumotlari topilmadi", 'warning')
        return redirect(url_for('accounting.index'))
    
    excel_file = create_contracts_excel(payments, course_year)
    
    filename = f"kontraktlar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    if course_year:
        filename = f"kontraktlar_{course_year}-kurs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return Response(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

