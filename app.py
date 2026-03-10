import os
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "login"


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
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///app.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()
        _ensure_default_admin()

    @app.route("/")
    def index():
        latest_quotes = Quote.query.order_by(Quote.created_at.desc()).limit(5).all()
        latest_songs = Song.query.order_by(Song.created_at.desc()).limit(5).all()
        latest_videos = Video.query.order_by(Video.created_at.desc()).limit(5).all()
        return render_template(
            "index.html",
            latest_quotes=latest_quotes,
            latest_songs=latest_songs,
            latest_videos=latest_videos,
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


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
