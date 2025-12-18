import unittest
from flask.testing import FlaskClient
from app import app, get_db, hash_password, create_session
from io import BytesIO
import os

class TestMyYouTube(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['UPLOAD_FOLDER'] = 'test_uploads'
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        self.client = app.test_client()
        with get_db() as db:
            db.execute("DELETE FROM users")
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM videos")
            db.execute("DELETE FROM likes")
            db.execute("DELETE FROM comments")
            db.commit()

    def tearDown(self):
        for file in os.listdir(app.config['UPLOAD_FOLDER']):
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], file))
        os.rmdir(app.config['UPLOAD_FOLDER'])

    def test_hash_password(self):
        pw = "testpass"
        hashed = hash_password(pw)
        self.assertEqual(len(hashed), 64)
        self.assertNotEqual(hashed, pw)

    def test_register(self):
        response = self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertIn("token", data)
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT * FROM users WHERE email = ?", ("test@example.com",))
            user = cur.fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(user['password_hash'], hash_password("pass"))

    def test_register_existing(self):
        self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        response = self.client.post('/register', json={"email": "test@example.com", "password": "pass2"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json)

    def test_login(self):
        self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        response = self.client.post('/login', json={"email": "test@example.com", "password": "pass"})
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertIn("token", data)

    def test_login_wrong_pass(self):
        self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        response = self.client.post('/login', json={"email": "test@example.com", "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json)

    def test_upload_video_public(self):
        register_resp = self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        token = register_resp.json['token']
        self.client.set_cookie('token', token)  # Используй set_cookie вместо headers для правильной передачи cookie
        data = {
            'title': 'Test Video',
            'description': 'Desc',
            'file': (BytesIO(b'test data'), 'test.mp4')
        }
        response = self.client.post('/upload', data=data, content_type='multipart/form-data')
        print("Upload public response:", response.status_code, response.data.decode())  # Debug
        self.assertEqual(response.status_code, 302)
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT * FROM videos WHERE title = ?", ("Test Video",))
            video = cur.fetchone()
            self.assertIsNotNone(video)
            self.assertEqual(video['private'], 0)
            self.assertTrue(os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], video['filename'])))

    def test_upload_video_private(self):
        register_resp = self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        token = register_resp.json['token']
        self.client.set_cookie('token', token)
        data = {
            'title': 'Private Video',
            'description': 'Desc',
            'private': 'on',
            'file': (BytesIO(b'test data'), 'test.mp4')
        }
        response = self.client.post('/upload', data=data, content_type='multipart/form-data')
        print("Upload private response:", response.status_code, response.data.decode())  # Debug
        self.assertEqual(response.status_code, 302)
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT * FROM videos WHERE title = ?", ("Private Video",))
            video = cur.fetchone()
            self.assertIsNotNone(video)
            self.assertEqual(video['private'], 1)

    def test_view_public_video(self):
        register_resp = self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        token = register_resp.json['token']
        self.client.set_cookie('token', token)
        data = {
            'title': 'Test Video',
            'description': 'Desc',
            'file': (BytesIO(b'test data'), 'test.mp4')
        }
        self.client.post('/upload', data=data, content_type='multipart/form-data')
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT id FROM videos WHERE title = ?", ("Test Video",))
            video_id = cur.fetchone()['id']
        response = self.client.get(f'/video/{video_id}')
        self.assertEqual(response.status_code, 200)
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT views FROM videos WHERE id = ?", (video_id,))
            views = cur.fetchone()['views']
            self.assertEqual(views, 1)

    def test_like_video(self):
        register_resp = self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        token = register_resp.json['token']
        self.client.set_cookie('token', token)
        data = {
            'title': 'Test Video',
            'description': 'Desc',
            'file': (BytesIO(b'test data'), 'test.mp4')
        }
        self.client.post('/upload', data=data, content_type='multipart/form-data')
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT id FROM videos WHERE title = ?", ("Test Video",))
            video_id = cur.fetchone()['id']
        response = self.client.post(f'/like/{video_id}')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data['likes'], 1)
        response = self.client.post(f'/like/{video_id}')
        self.assertEqual(response.json['likes'], 0)

    def test_comment_video(self):
        register_resp = self.client.post('/register', json={"email": "test@example.com", "password": "pass"})
        token = register_resp.json['token']
        self.client.set_cookie('token', token)
        data = {
            'title': 'Test Video',
            'description': 'Desc',
            'file': (BytesIO(b'test data'), 'test.mp4')
        }
        self.client.post('/upload', data=data, content_type='multipart/form-data')
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT id FROM videos WHERE title = ?", ("Test Video",))
            video_id = cur.fetchone()['id']
        response = self.client.post(f'/comment/{video_id}', json={"text": "Test comment"})
        self.assertEqual(response.status_code, 200)
        with get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT text FROM comments WHERE video_id = ?", (video_id,))
            comment = cur.fetchone()
            self.assertEqual(comment['text'], "Test comment")

if __name__ == '__main__':
    unittest.main(verbosity=2)