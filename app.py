import os
import random
import re
from datetime import datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "login"

def _normalize_database_url(url: str) -> str:
    # Many hosts (and Neon) provide URLs that start with "postgres://".
    # SQLAlchemy expects the "postgresql" scheme, and we prefer psycopg (v3) driver.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), nullable=True)
    url = db.Column(db.String(500), nullable=True)  # Spotify/YouTube link, etc.
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)  # YouTube/Vimeo/etc.
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
    database_url = os.environ.get("DATABASE_URL", "sqlite:///app.db").strip()
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_database_url(database_url)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()
        _ensure_default_admin()
        _seed_starter_content_if_empty()

    @app.route("/")
    def index():
        latest_quotes = Quote.query.order_by(Quote.created_at.desc()).limit(5).all()
        latest_songs = Song.query.order_by(Song.created_at.desc()).limit(5).all()
        latest_videos = Video.query.order_by(Video.created_at.desc()).limit(5).all()
        media = _list_media_files()
        return render_template(
            "index.html",
            latest_quotes=latest_quotes,
            latest_songs=latest_songs,
            latest_videos=latest_videos,
            media=media,
        )

    @app.route("/quotes")
    def quotes():
        items = Quote.query.order_by(Quote.created_at.desc()).all()
        return render_template("quotes.html", items=items)

    @app.route("/songs")
    def songs():
        items = Song.query.order_by(Song.created_at.desc()).all()
        return render_template("songs.html", items=items)

    @app.route("/videos")
    def videos():
        items = Video.query.order_by(Video.created_at.desc()).all()
        return render_template("videos.html", items=items)

    @app.route("/bot")
    def bot():
        return render_template("bot.html")

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        payload = request.get_json(silent=True) or {}
        message = (payload.get("message") or "").strip()
        history = payload.get("history") or []

        if not message:
            return jsonify({"reply": "No."}), 400
        if len(message) > 1000:
            return jsonify({"reply": "No. Too long."}), 400
        if not isinstance(history, list):
            history = []

        reply = _rude_roye_reply(message, history)
        return jsonify({"reply": reply})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for("admin"))
            flash("Invalid username or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("index"))

    @app.route("/admin")
    @login_required
    def admin():
        quotes_count = Quote.query.count()
        songs_count = Song.query.count()
        videos_count = Video.query.count()
        return render_template(
            "admin.html",
            quotes_count=quotes_count,
            songs_count=songs_count,
            videos_count=videos_count,
        )

    @app.route("/admin/account", methods=["GET", "POST"])
    @login_required
    def admin_account():
        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not current_password or not new_password:
                flash("Current and new password are required.", "warning")
                return render_template("admin_account.html")

            if new_password != confirm_password:
                flash("New passwords do not match.", "warning")
                return render_template("admin_account.html")

            if len(new_password) < 8:
                flash("Use at least 8 characters for the new password.", "warning")
                return render_template("admin_account.html")

            from flask_login import current_user

            if not current_user.check_password(current_password):
                flash("Current password is incorrect.", "danger")
                return render_template("admin_account.html")

            current_user.set_password(new_password)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("admin"))

        return render_template("admin_account.html")

    @app.route("/admin/quotes/new", methods=["GET", "POST"])
    @login_required
    def admin_quote_new():
        if request.method == "POST":
            text = request.form.get("text", "").strip()
            author = request.form.get("author", "").strip() or None
            if not text:
                flash("Quote text is required.", "warning")
            else:
                db.session.add(Quote(text=text, author=author))
                db.session.commit()
                flash("Quote added.", "success")
                return redirect(url_for("quotes"))
        return render_template("admin_quote_form.html")

    @app.route("/admin/songs/new", methods=["GET", "POST"])
    @login_required
    def admin_song_new():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            artist = request.form.get("artist", "").strip() or None
            url = request.form.get("url", "").strip() or None
            note = request.form.get("note", "").strip() or None
            if not title:
                flash("Song title is required.", "warning")
            else:
                db.session.add(Song(title=title, artist=artist, url=url, note=note))
                db.session.commit()
                flash("Song added.", "success")
                return redirect(url_for("songs"))
        return render_template("admin_song_form.html")

    @app.route("/admin/videos/new", methods=["GET", "POST"])
    @login_required
    def admin_video_new():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            url = request.form.get("url", "").strip()
            note = request.form.get("note", "").strip() or None
            if not title or not url:
                flash("Video title and URL are required.", "warning")
            else:
                db.session.add(Video(title=title, url=url, note=note))
                db.session.commit()
                flash("Video added.", "success")
                return redirect(url_for("videos"))
        return render_template("admin_video_form.html")

    return app


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


def _ensure_default_admin() -> None:
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = User.query.filter_by(username=username).first()
    if existing:
        return
    user = User(username=username, is_admin=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

def _list_media_files():
    media_dir = os.path.join(os.path.dirname(__file__), "static", "media")
    exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm"}
    items = []
    try:
        for name in sorted(os.listdir(media_dir)):
            _, ext = os.path.splitext(name.lower())
            if ext in exts and not name.startswith("."):
                items.append(name)
    except FileNotFoundError:
        return []
    return items[:24]


def _seed_starter_content_if_empty() -> None:
    if Quote.query.count() or Song.query.count() or Video.query.count():
        return

    starter_quotes = [
        ("You can be soft with me. I’ll still be dangerous for you.", "Rude Roye"),
        ("Love me like a promise. Threaten me like a habit.", "Sathee Roy"),
        ("If you give me a dhamki, at least make it cute.", "Rude Roye"),
        ("Dark romance rule: I act tough, but I’m yours.", "Rude Roye"),
        ("Biryani first. Then feelings. In that order.", "Rude Roye"),
        ("Cats, dogs, and you—my three favorite distractions.", "Rude Roye"),
        ("We’ll watch Friends and pretend we’re emotionally stable.", "Rude Roye"),
    ]
    for text, author in starter_quotes:
        db.session.add(Quote(text=text, author=author))

    starter_songs = [
        ("Leke Meri Kali Kali Car", None, None, "Your vibe: chaos + cute."),
        ("Friends Theme Song (I’ll be there for you)", None, None, "Yes, I know. Don’t judge me."),
        ("A ‘biryani date’ playlist", None, None, "Make it spicy. Like you."),
    ]
    for title, artist, url, note in starter_songs:
        db.session.add(Song(title=title, artist=artist, url=url, note=note))

    db.session.commit()


def _rude_roye_reply(message: str, history) -> str:
    text = message.strip()
    low = text.lower()

    # light safety: keep it playful, no harassment.
    if any(w in low for w in ["kill", "suicide", "self harm", "self-harm"]):
        return "No. Take a breath. Talk to a real human right now. I’m not built for this."

    def pick(options):
        seed = hash((low, len(history), datetime.utcnow().strftime("%Y-%m-%d%H")))
        rng = random.Random(seed)
        return rng.choice(options)

    if re.search(r"\b(hi|hello|hey|hii|yo)\b", low):
        return pick(
            [
                "No.",
                "Haan? Jaldi bol.",
                "Speak. I’m busy being iconic.",
                "What. Do you want biryani or drama?",
            ]
        )

    if "biryani" in low:
        return pick(
            [
                "Biryani is the only green flag I respect. Next.",
                "No talking. Order biryani. Then you can breathe.",
                "If it’s not biryani, I said no.",
            ]
        )

    if "cat" in low or "cats" in low:
        return pick(
            [
                "Cats are superior. You’re… trying.",
                "Fine. You can pet the cat. Not my ego though.",
                "Me: rude. Cat: ruder. Perfect family.",
            ]
        )

    if "dog" in low or "dogs" in low:
        return pick(
            [
                "Dogs are loyal. Unlike your attention span.",
                "Ok. Dogs get a yes. You get a maybe.",
                "If a dog likes you, I’ll consider not saying no.",
            ]
        )

    if "friends" in low:
        return pick(
            [
                "We’re watching Friends. You’re the Joey. I’m the sarcasm.",
                "No. Unless you bring snacks and don’t talk during the episode.",
                "Could you BE any more obsessed? Same. Next.",
            ]
        )

    if "dhamki" in low or "threat" in low:
        return pick(
            [
                "Give dhamki properly. With style. Otherwise no.",
                "Threaten me again and I’ll… still come back. Annoying, right?",
                "Dhamki accepted. Terms: you stay, I pretend I don’t care.",
            ]
        )

    if "love" in low or "miss" in low:
        return pick(
            [
                "No. (Yes.)",
                "Miss you too. Don’t make it weird.",
                "Say it again. I like the audacity.",
                "I’m not romantic. I’m just… selectively soft.",
            ]
        )

    if "song" in low or "music" in low:
        return pick(
            [
                "Play something dramatic. We have standards.",
                "No sad songs. Only ‘main character’ songs.",
                "Send link. I’ll judge silently. Loudly.",
            ]
        )

    # default: rude but flirty
    return pick(
        [
            "No.",
            "Ask better questions.",
            "I’m listening. Unfortunately.",
            "Try again. With confidence.",
            "Hmm. Still no.",
            "Fine. Maybe. Don’t get used to it.",
        ]
    )


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
