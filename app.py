from flask import Flask, render_template, redirect, request, url_for, flash, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port)

import pytesseract
from PIL import Image
import uuid
import re
import csv
from io import BytesIO


# --- Set path to Tesseract OCR ---
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Change if installed elsewhere

# --- Flask setup ---
app = Flask(__name__)
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Login manager setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Initialize database ---
def init_db():
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    with sqlite3.connect("database.db") as conn:
        cursor = conn.cursor()
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            );
        """)
        # Cards table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                email TEXT,
                phone TEXT,
                company TEXT,
                raw_text TEXT,
                image_path TEXT,
                upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    print("✅ Database and tables ready")

# --- User class ---
class User(UserMixin):
    def __init__(self, id_, username):
        self.id = id_
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect("database.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
    return User(user[0], user[1]) if user else None

# --- Routes ---

@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        with sqlite3.connect("database.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, password FROM users WHERE username = ?", (username,))
            result = cursor.fetchone()

        if result and check_password_hash(result[1], password):
            user = User(result[0], username)
            login_user(user)
            return redirect(url_for("dashboard"))
        return "❌ Invalid credentials"

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])

        try:
            with sqlite3.connect("database.db") as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return "❌ Username already exists"

    return render_template("login.html")

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    name = company = email = phone = ""
    if request.method == "POST":
        file = request.files.get("card_image")
        if file and file.filename != "":
            filename = f"{uuid.uuid4().hex}_{file.filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            # OCR: extract text
            image = Image.open(filepath)
            raw_text = pytesseract.image_to_string(image)

            # Extract fields
            lines = raw_text.strip().split("\n")
            lines = [line.strip() for line in lines if line.strip()]
            name = lines[0] if lines else ""
            company = lines[1] if len(lines) > 1 else ""
            emails = re.findall(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", raw_text)
            phones = re.findall(r"\+?\d[\d\s\-]{7,}\d", raw_text)
            email = emails[0] if emails else ""
            phone = phones[0] if phones else ""

            # Save to DB
            with sqlite3.connect("database.db") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO cards (user_id, name, company, email, phone, raw_text, image_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    current_user.id,
                    name,
                    company,
                    email,
                    phone,
                    raw_text,
                    filename
                ))
                conn.commit()

    return render_template("dashboard.html", username=current_user.username, name=name, company=company, email=email, phone=phone)

@app.route("/cards", methods=["GET", "POST"])
@login_required
def view_cards():
    search_query = request.form.get("search", "").strip()

    with sqlite3.connect("database.db") as conn:
        cursor = conn.cursor()
        if search_query:
            cursor.execute("""
                SELECT name, company, email, phone, upload_time
                FROM cards
                WHERE user_id = ?
                AND (
                    name LIKE ? OR
                    company LIKE ? OR
                    email LIKE ?
                )
                ORDER BY upload_time DESC
            """, (
                current_user.id,
                f"%{search_query}%",
                f"%{search_query}%",
                f"%{search_query}%"
            ))
        else:
            cursor.execute("""
                SELECT name, company, email, phone, upload_time
                FROM cards
                WHERE user_id = ?
                ORDER BY upload_time DESC
            """, (current_user.id,))
        cards = cursor.fetchall()

    return render_template("cards.html", cards=cards, username=current_user.username, search=search_query)

@app.route("/export")
@login_required
def export_csv():
    with sqlite3.connect("database.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, company, email, phone, upload_time
            FROM cards
            WHERE user_id = ?
            ORDER BY upload_time DESC
        """, (current_user.id,))
        cards = cursor.fetchall()

    # Write CSV to a binary buffer
    output = BytesIO()
    output.write("Name,Company,Email,Phone,Uploaded On\n".encode('utf-8'))
    for card in cards:
        line = ','.join(str(field).replace(",", " ") for field in card) + "\n"
        output.write(line.encode('utf-8'))

    output.seek(0)
    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name="visiting_cards.csv"
    )


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# --- Start app ---
if __name__ == "__main__":
    init_db()
    app.run(debug=True)

if __name__ == '__main__':
    app.run(debug=True)
