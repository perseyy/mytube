from flask import Flask, request, render_template, send_from_directory, redirect, url_for, make_response
import sqlite3
import os
import uuid
import hashlib
import datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def get_db():
    conn = sqlite3.connect('videos.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            password_hash TEXT,
            reg_date TEXT
        )
        ''')
        db.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            owner_id TEXT,
            filename TEXT,
            private INTEGER DEFAULT 0,
            upload_date TEXT,
            views INTEGER DEFAULT 0
        )
        ''')
        db.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            video_id TEXT,
            user_id TEXT,
            PRIMARY KEY (video_id, user_id)
        )
        ''')
        db.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            video_id TEXT,
            user_id TEXT,
            text TEXT,
            date TEXT
        )
        ''')
        db.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT
        )
        ''')
        db.commit()

init_db()

# Хэширование пароля
def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# Декоратор авторизации
def login_required(f):
    def decorated(*args, **kwargs):
        token = request.cookies.get('token')
        if not token:
            return redirect('/?login=1')
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
            row = cur.fetchone()
            if not row:
                return redirect('/?login=1')
            request.user_id = row['user_id']
            request.token = token
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

# Создание сессии
def create_session(user_id):
    token = str(uuid.uuid4())
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        db.commit()
    return token

# 1. Главная
@app.route('/')
def home():
    open_login = request.args.get('login') == '1'
    with get_db() as db:
        cur = db.cursor()
        cur.execute("SELECT * FROM videos WHERE private = 0 ORDER BY upload_date DESC")
        videos_list = cur.fetchall()
        is_logged_in = request.cookies.get('token') is not None
    return render_template('home.html', videos_list=videos_list, is_logged_in=is_logged_in, open_login=open_login)

# 2. Просмотр видео
@app.route('/video/<video_id>')
def view_video(video_id):
    with get_db() as db:
        cur = db.cursor()
        cur.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        video = cur.fetchone()
        if not video:
            return "Видео не найдено", 404

        if video['private']:
            token = request.cookies.get('token')
            if not token:
                return redirect('/?login=1')
            cur.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
            row = cur.fetchone()
            if not row or row['user_id'] != video['owner_id']:
                return "Доступ запрещён", 403

        cur.execute("UPDATE videos SET views = views + 1 WHERE id = ?", (video_id,))
        db.commit()

        cur.execute("SELECT COUNT(*) AS likes FROM likes WHERE video_id = ?", (video_id,))
        likes_count = cur.fetchone()['likes']

        cur.execute("SELECT text, date FROM comments WHERE video_id = ? ORDER BY date DESC", (video_id,))
        comments_list = cur.fetchall()

        is_logged_in = request.cookies.get('token') is not None

    return render_template('video.html', video=video, likes=likes_count, comments=comments_list, is_logged_in=is_logged_in)

# 3–4. Лайк и комментарий (без изменений)
@app.route('/like/<video_id>', methods=['POST'])
def toggle_like(video_id):
    token = request.cookies.get('token')
    if not token:
        return {"error": "Требуется авторизация"}, 401
    with get_db() as db:
        cur = db.cursor()
        cur.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
        user = cur.fetchone()
        if not user:
            return {"error": "Требуется авторизация"}, 401
        user_id = user['user_id']
        cur.execute("SELECT 1 FROM likes WHERE video_id = ? AND user_id = ?", (video_id, user_id))
        if cur.fetchone():
            cur.execute("DELETE FROM likes WHERE video_id = ? AND user_id = ?", (video_id, user_id))
        else:
            cur.execute("INSERT INTO likes (video_id, user_id) VALUES (?, ?)", (video_id, user_id))
        db.commit()
        cur.execute("SELECT COUNT(*) AS cnt FROM likes WHERE video_id = ?", (video_id,))
        likes = cur.fetchone()['cnt']
    return {"likes": likes}

@app.route('/comment/<video_id>', methods=['POST'])
def add_comment(video_id):
    token = request.cookies.get('token')
    if not token:
        return {"error": "Требуется авторизация"}, 401
    with get_db() as db:
        cur = db.cursor()
        cur.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
        user = cur.fetchone()
        if not user:
            return {"error": "Требуется авторизация"}, 401
        data = request.get_json()
        text = data.get('text')
        if not text:
            return {"error": "Текст обязателен"}, 400
        comment_id = str(uuid.uuid4())
        date = datetime.datetime.now().isoformat()
        cur.execute("INSERT INTO comments (id, video_id, user_id, text, date) VALUES (?, ?, ?, ?, ?)",
                    (comment_id, video_id, user['user_id'], text, date))
        db.commit()
    return {"success": True}

# 5. Загрузка
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'GET':
        return render_template('upload.html')

    file = request.files.get('file')
    if not file or file.filename == '':
        return "Файл не выбран", 400

    video_id = str(uuid.uuid4())
    filename = f"{video_id}_{file.filename}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    title = request.form.get('title', 'Без названия')
    description = request.form.get('description', '')
    is_private = 1 if 'private' in request.form else 0
    upload_date = datetime.datetime.now().isoformat()

    with get_db() as db:
        db.execute('''
            INSERT INTO videos (id, title, description, owner_id, filename, private, upload_date, views)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        ''', (video_id, title, description, request.user_id, filename, is_private, upload_date))
        db.commit()

    return redirect('/')

# 6–10. Файлы, регистрация, логин
@app.route('/video_file/<path:filename>')
def video_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/thumbnail/<path:filename>')
def thumbnail(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    with get_db() as db:
        cur = db.cursor()
        cur.execute("SELECT 1 FROM users WHERE email = ?", (email,))
        if cur.fetchone():
            return {"error": "Пользователь уже существует"}, 409
        user_id = str(uuid.uuid4())
        db.execute("INSERT INTO users (id, email, password_hash, reg_date) VALUES (?, ?, ?, ?)",
                   (user_id, email, hash_password(password), datetime.datetime.now().isoformat()))
        db.commit()
    token = create_session(user_id)
    return {"token": token}

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    with get_db() as db:
        cur = db.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,))
        user = cur.fetchone()
        if not user or user['password_hash'] != hash_password(password):
            return {"error": "Неверный email или пароль"}, 401
        token = create_session(user['id'])
    return {"token": token}

if __name__ == '__main__':
    app.run(debug=True, port=5000)