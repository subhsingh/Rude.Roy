import os
import random
import re
from datetime import datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
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
    app.config["REQUIRE_LOGIN"] = os.environ.get("REQUIRE_LOGIN", "true").lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()
        _ensure_default_admin()
        _seed_starter_content_if_empty()

    @app.before_request
    def _login_first_guard():
        if not app.config.get("REQUIRE_LOGIN", False):
            return None

        if request.endpoint in {None, "static", "login", "logout"}:
            return None
        if request.endpoint and request.endpoint.startswith("admin"):
            return None
        if request.path.startswith("/api/"):
            # allow chat API only when logged in (keeps "login first" consistent)
            if current_user.is_authenticated:
                return None
            return jsonify({"reply": "No. Login first."}), 401

        if not current_user.is_authenticated:
            return redirect(url_for("login", next=request.full_path))
        return None

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
                nxt = request.args.get("next") or ""
                if nxt.startswith("/") and not nxt.startswith("//"):
                    return redirect(nxt)
                return redirect(url_for("index"))
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
    username = os.environ.get("ADMIN_USERNAME", "Sathee.Singh")
    password = os.environ.get("ADMIN_PASSWORD", "Loveusubham")
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
                "No. You don’t just say hi and walk away. What do you actually want?",
                "Hello. Now finish the sentence. I don’t read minds, I just judge them.",
                "Hey. You get three questions today. Spend them wisely.",
                "Haan, bol. Biryani, drama, or emotional damage—pick one.",
            ]
        )

    if "biryani" in low:
        return pick(
            [
                "Biryani is the only green flag I fully respect. Bring that, and I might even say yes once.",
                "First biryani, then feelings. I’m not discussing anything serious on an empty plate.",
                "If it’s not biryani, it’s a no. If it is biryani… it’s a dangerous maybe.",
            ]
        )

    if "cat" in low or "cats" in low:
        return pick(
            [
                "Cats are superior creatures. You’re somewhere below them but slightly above the Wi‑Fi router.",
                "Fine, we can get a cat. You can pet the cat. My ego is strictly no‑touch.",
                "Me: rude. Cat: ruder. You: the only one allowed to stay.",
            ]
        )

    if "dog" in low or "dogs" in low:
        return pick(
            [
                "Dogs are loyal. Unlike your decision making. Somehow I still like you.",
                "Dogs get an automatic yes. You get a conditional maybe with terms and conditions.",
                "If a dog likes you, I’m contractually obligated to reduce my rudeness by 3%.",
            ]
        )

    if "friends" in low:
        return pick(
            [
                "We’re watching Friends. You’re Joey, obviously. I’m the sarcastic background commentary.",
                "Fine, we’ll watch Friends again. But you’re handling snacks and you’re not allowed to talk during my favorite lines.",
                "Could you BE any more obsessed? Same. Press play before I change my mind.",
            ]
        )

    if "dhamki" in low or "threat" in low:
        return pick(
            [
                "If you’re giving me a dhamki, at least add some poetry to it. I like my threats aesthetic.",
                "Threaten me all you want, I’ll still show up. That’s the problem and the promise.",
                "Dhamki accepted. Fine print: you stay, I act rude, both of us know it’s fake.",
            ]
        )

    if "love" in low or "miss" in low:
        return pick(
            [
                "No. (Which obviously means yes, but I’m not giving you the satisfaction.)",
                "Miss you too. There, I said it. Screenshot it before I deny everything later.",
                "Say it again. I like when you’re shameless about it.",
                "I’m not romantic. I’m just catastrophically soft for one specific person. Annoying, right?",
            ]
        )

    if "song" in low or "music" in low:
        return pick(
            [
                "Play something dramatic. Main character energy only, no side‑character playlists allowed.",
                "No sad songs unless we’re specifically choosing violence against our own feelings.",
                "Send me the link. I’ll judge the song and secretly add it to ‘our’ playlist.",
            ]
        )

    # default: rude but flirty
    return pick(
        [
            "No. But I’m still here, so that counts for something.",
            "Ask better questions. You’re interesting, act like it.",
            "I’m listening. Unfortunately for both of us.",
            "Try again, this time like you actually know I like you.",
            "Hmm. Still no… but I’m smiling a little. Tiny bit.",
            "Fine. Maybe. Don’t get used to it. (You absolutely will.)",
        ]
    )


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
