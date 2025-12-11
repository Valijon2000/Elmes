from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, PasswordResetToken
from app import db
from datetime import datetime, timedelta
import secrets

bp = Blueprint('auth', __name__)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash("Sizning hisobingiz bloklangan", 'error')
                return render_template('auth/login.html')
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.dashboard'))
        else:
            flash("Email yoki parol noto'g'ri", 'error')
    
    return render_template('auth/login.html')

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Tizimdan muvaffaqiyatli chiqdingiz", 'success')
    return redirect(url_for('auth.login'))

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        password = request.form.get('password')
        password2 = request.form.get('password2')
        
        if password != password2:
            flash("Parollar mos kelmaydi", 'error')
            return render_template('auth/register.html')
        
        if User.query.filter_by(email=email).first():
            flash("Bu email allaqachon ro'yxatdan o'tgan", 'error')
            return render_template('auth/register.html')
        
        user = User(email=email, full_name=full_name, role='student')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash("Muvaffaqiyatli ro'yxatdan o'tdingiz!", 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')

@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Parolni unutish sahifasi"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Faqat teacher, dean va student uchun
            if user.role not in ['teacher', 'dean', 'student']:
                flash("Bu funksiya faqat o'qituvchi, dekan va talabalar uchun mavjud", 'error')
                return render_template('auth/forgot_password.html')
            
            # Eski tokenlarni o'chirish
            PasswordResetToken.query.filter_by(user_id=user.id, is_used=False).delete()
            
            # Yangi token yaratish
            token = secrets.token_urlsafe(32)
            expires_at = datetime.utcnow() + timedelta(hours=1)  # 1 soat muddat
            
            reset_token = PasswordResetToken(
                user_id=user.id,
                token=token,
                expires_at=expires_at
            )
            db.session.add(reset_token)
            db.session.commit()
            
            # Token bilan reset sahifasiga yo'naltirish
            flash("Parolni tiklash uchun quyidagi havolaga o'ting", 'success')
            return redirect(url_for('auth.reset_password', token=token))
        else:
            flash("Bu email bilan foydalanuvchi topilmadi", 'error')
    
    return render_template('auth/forgot_password.html')

@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Parolni tiklash sahifasi"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    reset_token = PasswordResetToken.query.filter_by(token=token, is_used=False).first()
    
    if not reset_token:
        flash("Token topilmadi yoki allaqachon ishlatilgan", 'error')
        return redirect(url_for('auth.forgot_password'))
    
    if datetime.utcnow() > reset_token.expires_at:
        flash("Token muddati tugagan. Iltimos, yangi so'rov yuboring", 'error')
        reset_token.is_used = True
        db.session.commit()
        return redirect(url_for('auth.forgot_password'))
    
    user = reset_token.user
    
    if request.method == 'POST':
        password = request.form.get('password')
        password2 = request.form.get('password2')
        
        if password != password2:
            flash("Parollar mos kelmaydi", 'error')
            return render_template('auth/reset_password.html', token=token, user=user)
        
        if len(password) < 6:
            flash("Parol kamida 6 ta belgidan iborat bo'lishi kerak", 'error')
            return render_template('auth/reset_password.html', token=token, user=user)
        
        # Parolni o'zgartirish
        user.set_password(password)
        reset_token.is_used = True
        db.session.commit()
        
        flash("Parol muvaffaqiyatli o'zgartirildi! Endi tizimga kiring", 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html', token=token, user=user)

