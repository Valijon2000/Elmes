import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_from_directory, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.models import Subject, Lesson, Assignment, Submission, User, TeacherSubject, Group, LessonView
from app import db
from datetime import datetime


def allowed_video(filename):
    """Video fayl tekshirish"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config.get('ALLOWED_VIDEO_EXTENSIONS', {'mp4', 'webm', 'ogg'})

def allowed_submission_file(filename):
    """Topshiriq fayl tekshirish"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config.get('ALLOWED_SUBMISSION_EXTENSIONS', {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png'})

bp = Blueprint('courses', __name__, url_prefix='/subjects')

@bp.route('/')
@login_required
def index():
    """Fanlar ro'yxati"""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    
    if current_user.role == 'student':
        # Talaba faqat o'z guruhiga biriktirilgan fanlarni ko'radi
        if current_user.group_id:
            subject_ids = [ts.subject_id for ts in TeacherSubject.query.filter_by(group_id=current_user.group_id).all()]
            query = Subject.query.filter(Subject.id.in_(subject_ids))
        else:
            query = Subject.query.filter(False)  # Bo'sh
    elif current_user.role == 'teacher':
        # O'qituvchi faqat o'ziga biriktirilgan fanlarni ko'radi
        subject_ids = [ts.subject_id for ts in TeacherSubject.query.filter_by(teacher_id=current_user.id).all()]
        query = Subject.query.filter(Subject.id.in_(subject_ids))
    else:
        # Admin va dekan barcha fanlarni ko'radi
        query = Subject.query
    
    if search:
        query = query.filter(
            (Subject.name.ilike(f'%{search}%')) |
            (Subject.code.ilike(f'%{search}%'))
        )
    
    subjects = query.order_by(Subject.code).paginate(page=page, per_page=12)
    
    # Talaba uchun har bir fan bo'yicha ballar
    subject_grades = {}
    if current_user.role == 'student' and current_user.group_id:
        for subject in subjects.items:
            assignments = Assignment.query.filter_by(
                subject_id=subject.id,
                group_id=current_user.group_id
            ).all()
            
            # O'qituvchi biriktirishlari
            maruza_teacher = TeacherSubject.query.filter_by(
                subject_id=subject.id,
                group_id=current_user.group_id,
                lesson_type='maruza'
            ).first()
            
            amaliyot_teacher = TeacherSubject.query.filter_by(
                subject_id=subject.id,
                group_id=current_user.group_id,
                lesson_type='amaliyot'
            ).first()
            
            maruza_score = 0
            maruza_max = 0
            amaliyot_score = 0
            amaliyot_max = 0
            
            for assignment in assignments:
                submission = Submission.query.filter_by(
                    student_id=current_user.id,
                    assignment_id=assignment.id
                ).first()
                
                if submission and submission.score is not None:
                    assignment_creator = User.query.get(assignment.created_by) if assignment.created_by else None
                    
                    is_maruza = False
                    is_amaliyot = False
                    
                    if maruza_teacher and assignment_creator and assignment_creator.id == maruza_teacher.teacher_id:
                        is_maruza = True
                    elif amaliyot_teacher and assignment_creator and assignment_creator.id == amaliyot_teacher.teacher_id:
                        is_amaliyot = True
                    else:
                        # Agar o'qituvchi biriktirilmagan bo'lsa, topshiriq nomiga qarab aniqlash
                        assignment_title_lower = assignment.title.lower()
                        if 'amaliy' in assignment_title_lower or 'amaliyot' in assignment_title_lower:
                            is_amaliyot = True
                        else:
                            is_maruza = True
                    
                    if is_maruza:
                        maruza_score += submission.score
                        maruza_max += assignment.max_score
                    elif is_amaliyot:
                        amaliyot_score += submission.score
                        amaliyot_max += assignment.max_score
            
            subject_grades[subject.id] = {
                'maruza': {'score': maruza_score, 'max': maruza_max},
                'amaliyot': {'score': amaliyot_score, 'max': amaliyot_max},
                'total': {'score': maruza_score + amaliyot_score, 'max': maruza_max + amaliyot_max}
            }
    
    return render_template('courses/index.html', subjects=subjects, search=search, subject_grades=subject_grades)


@bp.route('/<int:id>')
@login_required
def detail(id):
    """Fan tafsilotlari"""
    subject = Subject.query.get_or_404(id)
    
    # Tekshirish: foydalanuvchi bu fanni ko'rishi mumkinmi
    can_view = False
    is_teacher = False
    my_group = None
    
    if current_user.role == 'admin':
        can_view = True
    elif current_user.role == 'dean':
        can_view = subject.faculty_id == current_user.faculty_id
    elif current_user.role == 'teacher':
        teaching = TeacherSubject.query.filter_by(
            teacher_id=current_user.id,
            subject_id=subject.id
        ).first()
        can_view = teaching is not None
        is_teacher = can_view
    elif current_user.role == 'student' and current_user.group_id:
        teaching = TeacherSubject.query.filter_by(
            group_id=current_user.group_id,
            subject_id=subject.id
        ).first()
        can_view = teaching is not None
        my_group = current_user.group
    
    if not can_view:
        flash("Sizda bu fanni ko'rish huquqi yo'q", 'error')
        return redirect(url_for('courses.index'))
    
    # Darslarni turi bo'yicha guruhlash
    all_lessons = subject.lessons.order_by(Lesson.order).all()
    maruza_lessons = [l for l in all_lessons if l.lesson_type == 'maruza']
    amaliyot_lessons = [l for l in all_lessons if l.lesson_type == 'amaliyot']
    
    # Talaba uchun: qaysi darslar qulflanganligini aniqlash
    lesson_locked_status = {}
    if current_user.role == 'student' and current_user.group_id:
        for lesson in all_lessons:
            # Faqat videoga ega darslar uchun qulf tekshiruvi
            if lesson.video_file or lesson.video_url:
                # Bir xil fan va dars turidagi oldingi darslarni olish
                previous_lessons = Lesson.query.filter(
                    Lesson.subject_id == subject.id,
                    Lesson.lesson_type == lesson.lesson_type,
                    Lesson.order < lesson.order
                ).order_by(Lesson.order).all()
                
                is_locked = False
                for prev_lesson in previous_lessons:
                    if prev_lesson.video_file or prev_lesson.video_url:
                        prev_lesson_view = LessonView.query.filter_by(
                            lesson_id=prev_lesson.id,
                            student_id=current_user.id
                        ).first()
                        
                        if not prev_lesson_view or not prev_lesson_view.is_completed:
                            is_locked = True
                            break
                
                lesson_locked_status[lesson.id] = is_locked
            else:
                lesson_locked_status[lesson.id] = False
    
    # Topshiriqlar
    if current_user.role == 'student' and current_user.group_id:
        assignments = subject.assignments.filter_by(group_id=current_user.group_id).all()
    elif current_user.role == 'teacher':
        # O'qituvchi o'zi dars beradigan guruhlarning topshiriqlarini ko'radi
        group_ids = [ts.group_id for ts in TeacherSubject.query.filter_by(
            teacher_id=current_user.id,
            subject_id=subject.id
        ).all()]
        assignments = subject.assignments.filter(Assignment.group_id.in_(group_ids)).all()
    else:
        assignments = subject.assignments.all()
    
    # Talaba uchun topshiriqlar holati va ballar
    assignment_status = {}
    student_grades = None
    if current_user.role == 'student':
        for assignment in assignments:
            submission = Submission.query.filter_by(
                student_id=current_user.id,
                assignment_id=assignment.id
            ).first()
            assignment_status[assignment.id] = submission
        
        # Ballarni hisoblash: amaliy, maruza va jami
        # O'qituvchi biriktirishlari bo'yicha
        maruza_teacher = TeacherSubject.query.filter_by(
            subject_id=subject.id,
            group_id=current_user.group_id,
            lesson_type='maruza'
        ).first()
        
        amaliyot_teacher = TeacherSubject.query.filter_by(
            subject_id=subject.id,
            group_id=current_user.group_id,
            lesson_type='amaliyot'
        ).first()
        
        maruza_score = 0
        maruza_max = 0
        amaliyot_score = 0
        amaliyot_max = 0
        
        for assignment in assignments:
            submission = assignment_status.get(assignment.id)
            if submission and submission.score is not None:
                # Topshiriq qaysi o'qituvchiga tegishli ekanligini aniqlash
                # Agar topshiriq yaratgan o'qituvchi maruza o'qituvchisi bo'lsa - maruza
                # Agar amaliyot o'qituvchisi bo'lsa - amaliyot
                assignment_creator = User.query.get(assignment.created_by) if assignment.created_by else None
                
                is_maruza = False
                is_amaliyot = False
                
                if maruza_teacher and assignment_creator and assignment_creator.id == maruza_teacher.teacher_id:
                    is_maruza = True
                elif amaliyot_teacher and assignment_creator and assignment_creator.id == amaliyot_teacher.teacher_id:
                    is_amaliyot = True
                else:
                    # Agar o'qituvchi biriktirilmagan bo'lsa, topshiriq nomiga qarab aniqlash
                    assignment_title_lower = assignment.title.lower()
                    if 'amaliy' in assignment_title_lower or 'amaliyot' in assignment_title_lower:
                        is_amaliyot = True
                    else:
                        is_maruza = True
                
                if is_maruza:
                    maruza_score += submission.score
                    maruza_max += assignment.max_score
                elif is_amaliyot:
                    amaliyot_score += submission.score
                    amaliyot_max += assignment.max_score
        
        student_grades = {
            'maruza': {'score': maruza_score, 'max': maruza_max},
            'amaliyot': {'score': amaliyot_score, 'max': amaliyot_max},
            'total': {'score': maruza_score + amaliyot_score, 'max': maruza_max + amaliyot_max}
        }
    
    # Fan bo'yicha o'qituvchilar (maruza va amaliyot bo'yicha ajratilgan)
    if current_user.role == 'student' and current_user.group_id:
        # Talaba uchun faqat o'z guruhidagi o'qituvchilar
        all_teacher_assignments = TeacherSubject.query.filter_by(
            subject_id=subject.id,
            group_id=current_user.group_id
        ).all()
        maruza_teachers = [ta for ta in all_teacher_assignments if ta.lesson_type == 'maruza']
        amaliyot_teachers = [ta for ta in all_teacher_assignments if ta.lesson_type == 'amaliyot']
        
        # Takrorlanuvchi o'qituvchilarni olib tashlash (faqat o'qituvchi obyektlari)
        maruza_teacher_ids = set()
        unique_maruza_teachers = []
        for ta in maruza_teachers:
            if ta.teacher_id not in maruza_teacher_ids:
                maruza_teacher_ids.add(ta.teacher_id)
                unique_maruza_teachers.append(ta.teacher)
        
        amaliyot_teacher_ids = set()
        unique_amaliyot_teachers = []
        for ta in amaliyot_teachers:
            if ta.teacher_id not in amaliyot_teacher_ids:
                amaliyot_teacher_ids.add(ta.teacher_id)
                unique_amaliyot_teachers.append(ta.teacher)
        
        maruza_teachers = unique_maruza_teachers
        amaliyot_teachers = unique_amaliyot_teachers
    else:
        # O'qituvchi, dekan, admin uchun barcha o'qituvchilar
        all_teacher_assignments = subject.teacher_assignments.all()
        maruza_teachers = [ta for ta in all_teacher_assignments if ta.lesson_type == 'maruza']
        amaliyot_teachers = [ta for ta in all_teacher_assignments if ta.lesson_type == 'amaliyot']
    
    return render_template('courses/detail.html',
                         subject=subject,
                         lessons=all_lessons,
                         maruza_lessons=maruza_lessons,
                         amaliyot_lessons=amaliyot_lessons,
                         assignments=assignments,
                         assignment_status=assignment_status,
                         maruza_teachers=maruza_teachers,
                         amaliyot_teachers=amaliyot_teachers,
                         is_teacher=is_teacher,
                         my_group=my_group,
                         student_grades=student_grades,
                         lesson_locked_status=lesson_locked_status)


@bp.route('/<int:id>/lessons/create', methods=['GET', 'POST'])
@login_required
def create_lesson(id):
    """Yangi dars yaratish"""
    subject = Subject.query.get_or_404(id)
    
    # Faqat o'qituvchi yoki admin dars yaratishi mumkin
    is_teacher = TeacherSubject.query.filter_by(
        teacher_id=current_user.id,
        subject_id=subject.id
    ).first() is not None
    
    if not is_teacher and current_user.role != 'admin':
        flash("Sizda dars yaratish uchun ruxsat yo'q", 'error')
        return redirect(url_for('courses.detail', id=id))
    
    if request.method == 'POST':
        video_filename = None
        lesson_file_url = None
        
        # Video fayl yuklash
        if 'video_file' in request.files:
            video = request.files['video_file']
            if video and video.filename and allowed_video(video.filename):
                # Unique fayl nomi
                ext = video.filename.rsplit('.', 1)[1].lower()
                video_filename = f"{uuid.uuid4().hex}.{ext}"
                video_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'videos', video_filename)
                video.save(video_path)
        
        # Video URL faqat YouTube link bo'lishi kerak
        video_url = request.form.get('video_url', '').strip()
        if video_url:
            # YouTube link tekshiruvi
            if 'youtube.com' not in video_url and 'youtu.be' not in video_url:
                flash("Video URL faqat YouTube link bo'lishi kerak (youtube.com yoki youtu.be)", 'error')
                return render_template('courses/create_lesson.html', subject=subject)
        
        # O'qituvchi uchun fayl yuklash majburiy
        if current_user.role == 'teacher' or current_user.role == 'admin':
            # Fayl yuklash
            if 'lesson_file' in request.files:
                lesson_file = request.files['lesson_file']
                if lesson_file and lesson_file.filename:
                    # Fayl formatini tekshirish
                    allowed_extensions = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'zip', 'rar'}
                    ext = lesson_file.filename.rsplit('.', 1)[1].lower() if '.' in lesson_file.filename else ''
                    if ext not in allowed_extensions:
                        flash("Ruxsat berilmagan fayl formati. Ruxsatli formatlar: PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, TXT, ZIP, RAR", 'error')
                        return render_template('courses/create_lesson.html', subject=subject)
                    
                    # Faylni saqlash
                    filename = f"{uuid.uuid4().hex}.{ext}"
                    files_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'lesson_files')
                    os.makedirs(files_folder, exist_ok=True)
                    file_path = os.path.join(files_folder, filename)
                    lesson_file.save(file_path)
                    lesson_file_url = filename
                else:
                    # URL orqali fayl
                    file_url_input = request.form.get('file_url', '').strip()
                    if file_url_input:
                        lesson_file_url = file_url_input
            
            # O'qituvchi uchun fayl majburiy
            if not lesson_file_url:
                flash("O'qituvchilar uchun mavzu faylini yuklash majburiy!", 'error')
                return render_template('courses/create_lesson.html', subject=subject)
        else:
            # Boshqa rollar uchun ixtiyoriy
            lesson_file_url = request.form.get('file_url', '').strip() or None
        
        lesson = Lesson(
            title=request.form.get('title'),
            content=request.form.get('content'),
            video_url=video_url if video_url else None,
            video_file=video_filename,
            file_url=lesson_file_url,
            duration=int(request.form.get('duration', 0) or 0),
            order=subject.lessons.count() + 1,
            lesson_type=request.form.get('lesson_type', 'maruza'),
            subject_id=id,
            created_by=current_user.id
        )
        db.session.add(lesson)
        db.session.commit()
        
        flash("Dars muvaffaqiyatli qo'shildi", 'success')
        return redirect(url_for('courses.detail', id=id))
    
    return render_template('courses/create_lesson.html', subject=subject)


@bp.route('/lessons/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_lesson(id):
    """Darsni tahrirlash"""
    lesson = Lesson.query.get_or_404(id)
    subject = lesson.subject
    
    # Faqat o'qituvchi yoki admin darsni tahrirlashi mumkin
    is_teacher = TeacherSubject.query.filter_by(
        teacher_id=current_user.id,
        subject_id=subject.id
    ).first() is not None
    
    if not is_teacher and current_user.role != 'admin':
        flash("Sizda darsni tahrirlash uchun ruxsat yo'q", 'error')
        return redirect(url_for('courses.lesson_detail', id=id))
    
    if request.method == 'POST':
        video_filename = lesson.video_file  # Eski faylni saqlash
        lesson_file_url = lesson.file_url  # Eski faylni saqlash
        
        # Video fayl yuklash (yangi fayl yuklansa, eski o'rniga yangisini qo'yish)
        if 'video_file' in request.files:
            video = request.files['video_file']
            if video and video.filename and allowed_video(video.filename):
                # Eski video faylni o'chirish
                if lesson.video_file:
                    old_video_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'videos', lesson.video_file)
                    if os.path.exists(old_video_path):
                        try:
                            os.remove(old_video_path)
                        except:
                            pass
                
                # Yangi video faylni saqlash
                ext = video.filename.rsplit('.', 1)[1].lower()
                video_filename = f"{uuid.uuid4().hex}.{ext}"
                video_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'videos', video_filename)
                video.save(video_path)
        
        # Video URL faqat YouTube link bo'lishi kerak
        video_url = request.form.get('video_url', '').strip()
        if video_url:
            # YouTube link tekshiruvi
            if 'youtube.com' not in video_url and 'youtu.be' not in video_url:
                flash("Video URL faqat YouTube link bo'lishi kerak (youtube.com yoki youtu.be)", 'error')
                return render_template('courses/edit_lesson.html', lesson=lesson, subject=subject)
            # Agar yangi URL kiritilgan bo'lsa, video_file ni None qilish va eski faylni o'chirish
            if lesson.video_file:
                old_video_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'videos', lesson.video_file)
                if os.path.exists(old_video_path):
                    try:
                        os.remove(old_video_path)
                    except:
                        pass
            video_filename = None
        elif not video_filename:
            # Agar yangi video yuklanmagan bo'lsa, eski videoni saqlash
            video_filename = lesson.video_file
            video_url = lesson.video_url
        
        # O'qituvchi uchun fayl yuklash
        if current_user.role == 'teacher' or current_user.role == 'admin':
            # Fayl yuklash
            if 'lesson_file' in request.files:
                lesson_file = request.files['lesson_file']
                if lesson_file and lesson_file.filename:
                    # Eski faylni o'chirish (agar yuklangan bo'lsa)
                    if lesson.file_url and not ('http://' in lesson.file_url or 'https://' in lesson.file_url):
                        old_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'lesson_files', lesson.file_url)
                        if os.path.exists(old_file_path):
                            try:
                                os.remove(old_file_path)
                            except:
                                pass
                    
                    # Fayl formatini tekshirish
                    allowed_extensions = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'zip', 'rar'}
                    ext = lesson_file.filename.rsplit('.', 1)[1].lower() if '.' in lesson_file.filename else ''
                    if ext not in allowed_extensions:
                        flash("Ruxsat berilmagan fayl formati. Ruxsatli formatlar: PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, TXT, ZIP, RAR", 'error')
                        return render_template('courses/edit_lesson.html', lesson=lesson, subject=subject)
                    
                    # Faylni saqlash
                    filename = f"{uuid.uuid4().hex}.{ext}"
                    files_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'lesson_files')
                    os.makedirs(files_folder, exist_ok=True)
                    file_path = os.path.join(files_folder, filename)
                    lesson_file.save(file_path)
                    lesson_file_url = filename
                else:
                    # URL orqali fayl
                    file_url_input = request.form.get('file_url', '').strip()
                    if file_url_input:
                        # Agar eski fayl yuklangan bo'lsa, o'chirish
                        if lesson.file_url and not ('http://' in lesson.file_url or 'https://' in lesson.file_url):
                            old_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'lesson_files', lesson.file_url)
                            if os.path.exists(old_file_path):
                                try:
                                    os.remove(old_file_path)
                                except:
                                    pass
                        lesson_file_url = file_url_input
                    else:
                        # Agar yangi fayl yoki URL kiritilmagan bo'lsa, eski faylni saqlash
                        lesson_file_url = lesson.file_url
                        if not lesson_file_url:
                            # Agar hech qanday fayl bo'lmasa, majburiy
                            flash("O'qituvchilar uchun mavzu faylini yuklash majburiy!", 'error')
                            return render_template('courses/edit_lesson.html', lesson=lesson, subject=subject)
        else:
            # Boshqa rollar uchun ixtiyoriy
            file_url_input = request.form.get('file_url', '').strip()
            if file_url_input:
                # Agar eski fayl yuklangan bo'lsa, o'chirish
                if lesson.file_url and not ('http://' in lesson.file_url or 'https://' in lesson.file_url):
                    old_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'lesson_files', lesson.file_url)
                    if os.path.exists(old_file_path):
                        try:
                            os.remove(old_file_path)
                        except:
                            pass
                lesson_file_url = file_url_input
            else:
                lesson_file_url = lesson.file_url  # Eski faylni saqlash
        
        # Dars ma'lumotlarini yangilash
        lesson.title = request.form.get('title')
        lesson.content = request.form.get('content')
        lesson.video_url = video_url if video_url else None
        lesson.video_file = video_filename
        lesson.file_url = lesson_file_url
        lesson.duration = int(request.form.get('duration', 0) or 0)
        lesson.lesson_type = request.form.get('lesson_type', 'maruza')
        
        db.session.commit()
        
        flash("Dars muvaffaqiyatli yangilandi", 'success')
        return redirect(url_for('courses.lesson_detail', id=id))
    
    return render_template('courses/edit_lesson.html', lesson=lesson, subject=subject)


@bp.route('/uploads/videos/<filename>')
@login_required
def serve_video(filename):
    """Video faylni uzatish"""
    videos_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'videos')
    return send_from_directory(videos_folder, filename)

@bp.route('/uploads/lesson_files/<filename>')
@login_required
def serve_lesson_file(filename):
    """Dars faylini uzatish"""
    files_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'lesson_files')
    file_path = os.path.join(files_folder, filename)
    
    # Fayl mavjudligini tekshirish
    if not os.path.exists(file_path):
        flash("Fayl topilmadi", 'error')
        return redirect(url_for('courses.index'))
    
    # Ruxsatni tekshirish
    lesson = Lesson.query.filter_by(file_url=filename).first()
    if not lesson:
        # URL bo'lsa, to'g'ridan-to'g'ri qaytarish
        return send_from_directory(files_folder, filename, as_attachment=True)
    
    subject = lesson.subject
    
    # Tekshirish
    can_view = False
    if current_user.role == 'admin':
        can_view = True
    elif current_user.role == 'teacher':
        can_view = TeacherSubject.query.filter_by(
            teacher_id=current_user.id,
            subject_id=subject.id
        ).first() is not None
    elif current_user.role == 'student' and current_user.group_id:
        can_view = TeacherSubject.query.filter_by(
            group_id=current_user.group_id,
            subject_id=subject.id
        ).first() is not None
    
    if not can_view:
        flash("Sizda bu faylni ko'rish huquqi yo'q", 'error')
        return redirect(url_for('courses.index'))
    
    return send_from_directory(files_folder, filename, as_attachment=True)

@bp.route('/uploads/submissions/<filename>')
@login_required
def serve_submission_file(filename):
    """Topshiriq faylini ko'rsatish"""
    submissions_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'submissions')
    file_path = os.path.join(submissions_folder, filename)
    
    # Fayl mavjudligini tekshirish
    if not os.path.exists(file_path):
        flash("Fayl topilmadi", 'error')
        return redirect(url_for('courses.index'))
    
    # Ruxsatni tekshirish - faqat fayl egasi yoki o'qituvchi ko'ra oladi
    submission = Submission.query.filter_by(file_url=filename).first()
    if not submission:
        flash("Fayl topilmadi", 'error')
        return redirect(url_for('courses.index'))
    
    # Talaba o'z faylini ko'ra oladi
    if current_user.role == 'student' and submission.student_id != current_user.id:
        flash("Sizda bu faylni ko'rish huquqi yo'q", 'error')
        return redirect(url_for('courses.index'))
    
    # O'qituvchi o'z guruhlaridagi talabalarning fayllarini ko'ra oladi
    if current_user.role == 'teacher':
        assignment = submission.assignment
        teaching = TeacherSubject.query.filter_by(
            teacher_id=current_user.id,
            subject_id=assignment.subject_id,
            group_id=assignment.group_id
        ).first()
        if not teaching:
            flash("Sizda bu faylni ko'rish huquqi yo'q", 'error')
            return redirect(url_for('courses.index'))
    
    return send_from_directory(submissions_folder, filename, as_attachment=True)


@bp.route('/lessons/<int:id>')
@login_required
def lesson_detail(id):
    """Dars tafsilotlari"""
    lesson = Lesson.query.get_or_404(id)
    subject = lesson.subject
    
    # Tekshirish
    can_view = False
    if current_user.role == 'admin':
        can_view = True
    elif current_user.role == 'dean':
        can_view = subject.faculty_id == current_user.faculty_id
    elif current_user.role == 'teacher':
        can_view = TeacherSubject.query.filter_by(
            teacher_id=current_user.id,
            subject_id=subject.id
        ).first() is not None
    elif current_user.role == 'student' and current_user.group_id:
        can_view = TeacherSubject.query.filter_by(
            group_id=current_user.group_id,
            subject_id=subject.id
        ).first() is not None
    
    if not can_view:
        flash("Sizda bu darsni ko'rish huquqi yo'q", 'error')
        return redirect(url_for('courses.index'))
    
    # Talaba uchun ko'rish yozuvi va qulflanganligini tekshirish
    lesson_view = None
    is_locked = False
    if current_user.role == 'student':
        lesson_view = LessonView.query.filter_by(
            lesson_id=lesson.id,
            student_id=current_user.id
        ).first()
        
        # Oldingi darslar to'liq ko'rilganligini tekshirish (faqat videoga ega darslar uchun)
        if lesson.video_file or lesson.video_url:
            previous_lessons = Lesson.query.filter(
                Lesson.subject_id == subject.id,
                Lesson.lesson_type == lesson.lesson_type,
                Lesson.order < lesson.order
            ).order_by(Lesson.order).all()
            
            for prev_lesson in previous_lessons:
                if prev_lesson.video_file or prev_lesson.video_url:
                    prev_lesson_view = LessonView.query.filter_by(
                        lesson_id=prev_lesson.id,
                        student_id=current_user.id
                    ).first()
                    
                    if not prev_lesson_view or not prev_lesson_view.is_completed:
                        is_locked = True
                        break
    
    return render_template('courses/lesson_detail.html', 
                         lesson=lesson, 
                         subject=subject,
                         lesson_view=lesson_view,
                         is_locked=is_locked)


@bp.route('/lessons/<int:id>/watch')
@login_required
def watch_video(id):
    """Video ko'rish sahifasi - diqqat tekshiruvi bilan"""
    lesson = Lesson.query.get_or_404(id)
    subject = lesson.subject
    
    if not lesson.video_file and not lesson.video_url:
        flash("Bu darsda video mavjud emas", 'warning')
        return redirect(url_for('courses.lesson_detail', id=id))
    
    # Tekshirish
    can_view = False
    if current_user.role == 'admin':
        can_view = True
    elif current_user.role == 'teacher':
        can_view = TeacherSubject.query.filter_by(
            teacher_id=current_user.id,
            subject_id=subject.id
        ).first() is not None
    elif current_user.role == 'student' and current_user.group_id:
        can_view = TeacherSubject.query.filter_by(
            group_id=current_user.group_id,
            subject_id=subject.id
        ).first() is not None
    
    if not can_view:
        flash("Sizda bu darsni ko'rish huquqi yo'q", 'error')
        return redirect(url_for('courses.index'))
    
    # Talaba uchun: oldingi darslar to'liq ko'rilganligini tekshirish
    is_locked = False
    if current_user.role == 'student':
        # Bir xil fan va dars turidagi oldingi darslarni olish
        previous_lessons = Lesson.query.filter(
            Lesson.subject_id == subject.id,
            Lesson.lesson_type == lesson.lesson_type,
            Lesson.order < lesson.order
        ).order_by(Lesson.order).all()
        
        # Har bir oldingi dars to'liq ko'rilganligini tekshirish
        for prev_lesson in previous_lessons:
            if prev_lesson.video_file or prev_lesson.video_url:  # Faqat videoga ega darslar
                prev_lesson_view = LessonView.query.filter_by(
                    lesson_id=prev_lesson.id,
                    student_id=current_user.id
                ).first()
                
                if not prev_lesson_view or not prev_lesson_view.is_completed:
                    is_locked = True
                    break
    
    if is_locked and current_user.role == 'student':
        flash("Avval oldingi videolarni to'liq ko'rib chiqing!", 'warning')
        return redirect(url_for('courses.lesson_detail', id=id))
    
    # Talaba uchun ko'rish yozuvini yaratish yoki olish
    lesson_view = None
    next_lesson = None
    if current_user.role == 'student':
        lesson_view = LessonView.query.filter_by(
            lesson_id=lesson.id,
            student_id=current_user.id
        ).first()
        
        if not lesson_view:
            lesson_view = LessonView(
                lesson_id=lesson.id,
                student_id=current_user.id
            )
            db.session.add(lesson_view)
            db.session.commit()
        
        # Keyingi darsni topish (bir xil fan va dars turida)
        next_lesson = Lesson.query.filter(
            Lesson.subject_id == subject.id,
            Lesson.lesson_type == lesson.lesson_type,
            Lesson.order > lesson.order,
            (Lesson.video_file != None) | (Lesson.video_url != None)
        ).order_by(Lesson.order).first()
    
    return render_template('courses/watch_video.html',
                         lesson=lesson,
                         subject=subject,
                         lesson_view=lesson_view,
                         next_lesson=next_lesson)


@bp.route('/lessons/<int:id>/attention-check', methods=['POST'])
@login_required
def attention_check(id):
    """Diqqat tekshiruvi API"""
    if current_user.role != 'student':
        return jsonify({'success': False, 'error': 'Faqat talabalar uchun'}), 403
    
    lesson = Lesson.query.get_or_404(id)
    
    lesson_view = LessonView.query.filter_by(
        lesson_id=lesson.id,
        student_id=current_user.id
    ).first()
    
    if not lesson_view:
        return jsonify({'success': False, 'error': 'Ko\'rish yozuvi topilmadi'}), 404
    
    # Diqqat tekshiruvidan o'tdi
    lesson_view.attention_checks_passed += 1
    
    # 3 ta tekshiruvdan o'tganmi?
    was_completed = lesson_view.is_completed
    if lesson_view.attention_checks_passed >= 3:
        lesson_view.is_completed = True
        lesson_view.completed_at = datetime.utcnow()
    
    db.session.commit()
    
    # Keyingi darsni topish (bir xil fan va dars turida)
    next_lesson = None
    if lesson_view.is_completed and not was_completed:
        next_lesson = Lesson.query.filter(
            Lesson.subject_id == lesson.subject_id,
            Lesson.lesson_type == lesson.lesson_type,
            Lesson.order > lesson.order,
            (Lesson.video_file != None) | (Lesson.video_url != None)
        ).order_by(Lesson.order).first()
    
    response = {
        'success': True,
        'checks_passed': lesson_view.attention_checks_passed,
        'is_completed': lesson_view.is_completed
    }
    
    if next_lesson:
        response['next_lesson'] = {
            'id': next_lesson.id,
            'title': next_lesson.title,
            'url': url_for('courses.watch_video', id=next_lesson.id)
        }
    
    return jsonify(response)


@bp.route('/lessons/<int:id>/update-watch-time', methods=['POST'])
@login_required
def update_watch_time(id):
    """Ko'rish vaqtini yangilash API"""
    if current_user.role != 'student':
        return jsonify({'success': False}), 403
    
    lesson_view = LessonView.query.filter_by(
        lesson_id=id,
        student_id=current_user.id
    ).first()
    
    if lesson_view:
        watch_duration = request.json.get('watch_duration', 0)
        lesson_view.watch_duration = max(lesson_view.watch_duration, watch_duration)
        db.session.commit()
        
        # Maksimal ko'rilgan vaqtni qaytarish
        return jsonify({
            'success': True,
            'watch_duration': lesson_view.watch_duration,
            'is_completed': lesson_view.is_completed
        })
    
    return jsonify({'success': True, 'watch_duration': 0})


@bp.route('/<int:id>/assignments/create', methods=['GET', 'POST'])
@login_required
def create_assignment(id):
    """Yangi topshiriq yaratish"""
    subject = Subject.query.get_or_404(id)
    
    # O'qituvchi dars beradigan guruhlar
    teacher_groups = TeacherSubject.query.filter_by(
        teacher_id=current_user.id,
        subject_id=subject.id
    ).all()
    
    if not teacher_groups and current_user.role != 'admin':
        flash("Sizda topshiriq yaratish uchun ruxsat yo'q", 'error')
        return redirect(url_for('courses.detail', id=id))
    
    groups = [tg.group for tg in teacher_groups]
    
    if request.method == 'POST':
        due_date_str = request.form.get('due_date')
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d') if due_date_str else None
        
        group_id = request.form.get('group_id', type=int)
        
        assignment = Assignment(
            title=request.form.get('title'),
            description=request.form.get('description'),
            max_score=int(request.form.get('max_score', 100)),
            due_date=due_date,
            subject_id=id,
            group_id=group_id,
            file_required=bool(request.form.get('file_required')),
            created_by=current_user.id
        )
        db.session.add(assignment)
        db.session.commit()
        
        flash("Topshiriq muvaffaqiyatli yaratildi", 'success')
        return redirect(url_for('courses.detail', id=id))
    
    return render_template('courses/create_assignment.html', subject=subject, groups=groups)


@bp.route('/assignments/<int:id>')
@login_required
def assignment_detail(id):
    """Topshiriq tafsilotlari"""
    assignment = Assignment.query.get_or_404(id)
    subject = assignment.subject
    
    # O'qituvchi yoki adminmi?
    is_teacher = TeacherSubject.query.filter_by(
        teacher_id=current_user.id,
        subject_id=subject.id,
        group_id=assignment.group_id
    ).first() is not None
    
    if is_teacher or current_user.role == 'admin':
        submissions = assignment.submissions.all()
        
        # Guruh talabalari
        group_students = User.query.filter_by(
            role='student',
            group_id=assignment.group_id
        ).all()
        
        # Topshirmagan talabalar
        submitted_ids = [s.student_id for s in submissions]
        not_submitted = [s for s in group_students if s.id not in submitted_ids]
        
        return render_template('courses/assignment_submissions.html',
                             assignment=assignment,
                             submissions=submissions,
                             not_submitted=not_submitted)
    else:
        submission = Submission.query.filter_by(
            student_id=current_user.id,
            assignment_id=id
        ).first()
        return render_template('courses/assignment_detail.html',
                             assignment=assignment,
                             submission=submission)


@bp.route('/assignments/<int:id>/submit', methods=['POST'])
@login_required
def submit_assignment(id):
    """Topshiriq topshirish"""
    if current_user.role != 'student':
        flash("Faqat talabalar topshiriq yuborishi mumkin", 'error')
        return redirect(url_for('courses.assignment_detail', id=id))
    
    assignment = Assignment.query.get_or_404(id)
    
    # Talaba shu guruhga tegishlimi?
    if assignment.group_id != current_user.group_id:
        flash("Bu topshiriq sizning guruhingiz uchun emas", 'error')
        return redirect(url_for('courses.index'))
    
    content = request.form.get('content', '').strip()
    file_url = None
    
    # Fayl yuklash
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            # Fayl formatini tekshirish
            if not allowed_submission_file(file.filename):
                flash("Ruxsat berilmagan fayl formati. Ruxsatli formatlar: PDF, DOC, DOCX, XLS, XLSX, JPG, JPEG, PNG, GIF, BMP, TXT, RTF", 'error')
                return redirect(url_for('courses.assignment_detail', id=id))
            
            # Fayl hajmini tekshirish (2 MB)
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            
            max_size = current_app.config.get('MAX_SUBMISSION_SIZE', 2 * 1024 * 1024)
            if file_size > max_size:
                flash(f"Fayl hajmi {max_size / (1024 * 1024):.0f} MB dan oshmasligi kerak", 'error')
                return redirect(url_for('courses.assignment_detail', id=id))
            
            # Faylni saqlash
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            submissions_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'submissions')
            file_path = os.path.join(submissions_folder, filename)
            file.save(file_path)
            file_url = filename
    
    # Fayl majburiy bo'lsa tekshirish
    if assignment.file_required and not file_url:
        flash("Bu topshiriq uchun fayl yuklash majburiy!", 'error')
        return redirect(url_for('courses.assignment_detail', id=id))
    
    # Agar na content, na file bo'lmasa
    if not content and not file_url:
        flash("Javob yoki fayl yuborishingiz kerak", 'error')
        return redirect(url_for('courses.assignment_detail', id=id))
    
    existing = Submission.query.filter_by(
        student_id=current_user.id,
        assignment_id=id
    ).first()
    
    if existing:
        existing.content = content
        if file_url:
            # Eski faylni o'chirish
            if existing.file_url:
                old_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'submissions', existing.file_url)
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                    except:
                        pass
            existing.file_url = file_url
        existing.submitted_at = datetime.utcnow()
        flash("Javobingiz yangilandi", 'success')
    else:
        submission = Submission(
            student_id=current_user.id,
            assignment_id=id,
            content=content,
            file_url=file_url
        )
        db.session.add(submission)
        flash("Javobingiz muvaffaqiyatli yuborildi", 'success')
    
    db.session.commit()
    return redirect(url_for('courses.assignment_detail', id=id))


@bp.route('/submissions/<int:id>/grade', methods=['POST'])
@login_required
def grade_submission(id):
    """Bahoni qo'yish"""
    submission = Submission.query.get_or_404(id)
    assignment = submission.assignment
    subject = assignment.subject
    
    # O'qituvchi yoki adminmi?
    is_teacher = TeacherSubject.query.filter_by(
        teacher_id=current_user.id,
        subject_id=subject.id,
        group_id=assignment.group_id
    ).first() is not None
    
    if not is_teacher and current_user.role != 'admin':
        flash("Sizda baho qo'yish uchun ruxsat yo'q", 'error')
        return redirect(url_for('courses.assignment_detail', id=assignment.id))
    
    submission.score = int(request.form.get('score', 0))
    submission.feedback = request.form.get('feedback')
    submission.graded_at = datetime.utcnow()
    submission.graded_by = current_user.id
    db.session.commit()
    
    flash("Baho muvaffaqiyatli qo'yildi", 'success')
    return redirect(url_for('courses.assignment_detail', id=assignment.id))


@bp.route('/grades')
@login_required
def grades():
    """Baholar"""
    if current_user.role == 'student':
        submissions = Submission.query.filter(
            Submission.student_id == current_user.id,
            Submission.score != None
        ).order_by(Submission.graded_at.desc()).all()
        
        # Fanlar bo'yicha guruhlash
        grades_by_subject = {}
        for sub in submissions:
            subject = sub.assignment.subject
            if subject.id not in grades_by_subject:
                grades_by_subject[subject.id] = {
                    'subject': subject,
                    'submissions': [],
                    'total_score': 0,
                    'max_score': 0
                }
            grades_by_subject[subject.id]['submissions'].append(sub)
            grades_by_subject[subject.id]['total_score'] += sub.score
            grades_by_subject[subject.id]['max_score'] += sub.assignment.max_score
        
        return render_template('courses/grades.html', grades_by_subject=grades_by_subject)
    
    elif current_user.role == 'teacher':
        # O'qituvchining fanlari va guruhlari
        teacher_assignments = TeacherSubject.query.filter_by(teacher_id=current_user.id).all()
        
        subject_groups = {}
        for ta in teacher_assignments:
            if ta.subject.id not in subject_groups:
                subject_groups[ta.subject.id] = {
                    'subject': ta.subject,
                    'groups': []
                }
            subject_groups[ta.subject.id]['groups'].append(ta.group)
        
        return render_template('courses/teacher_grades.html', subject_groups=subject_groups)
    
    else:
        return redirect(url_for('main.dashboard'))


@bp.route('/grades/<int:subject_id>/<int:group_id>')
@login_required
def group_grades(subject_id, group_id):
    """Guruh baholari"""
    subject = Subject.query.get_or_404(subject_id)
    group = Group.query.get_or_404(group_id)
    
    # Tekshirish
    is_teacher = TeacherSubject.query.filter_by(
        teacher_id=current_user.id,
        subject_id=subject_id,
        group_id=group_id
    ).first() is not None
    
    if not is_teacher and current_user.role not in ['admin', 'dean']:
        flash("Sizda bu sahifani ko'rish huquqi yo'q", 'error')
        return redirect(url_for('courses.grades'))
    
    # Guruh talabalari
    students = User.query.filter_by(role='student', group_id=group_id).order_by(User.full_name).all()
    
    # Fan topshiriqlari
    assignments = Assignment.query.filter_by(subject_id=subject_id, group_id=group_id).all()
    
    # Har bir talabaning baholari
    student_grades = {}
    for student in students:
        student_grades[student.id] = {
            'student': student,
            'submissions': {},
            'total': 0,
            'max_total': 0
        }
        for assignment in assignments:
            submission = Submission.query.filter_by(
                student_id=student.id,
                assignment_id=assignment.id
            ).first()
            student_grades[student.id]['submissions'][assignment.id] = submission
            if submission and submission.score:
                student_grades[student.id]['total'] += submission.score
            student_grades[student.id]['max_total'] += assignment.max_score
    
    return render_template('courses/group_grades.html',
                         subject=subject,
                         group=group,
                         students=students,
                         assignments=assignments,
                         student_grades=student_grades)
