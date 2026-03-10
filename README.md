# For You (Flask)

A small **public** (viewable by anyone) love-site you can open on **mobile + desktop**, built with **Python (Flask)**.

- Public pages: Quotes, Songs, Videos
- Admin (login required): Add new quotes/songs/videos
- Database: SQLite (`app.db`)

## Run locally (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Optional: set your admin login
$env:ADMIN_USERNAME="yourname"
$env:ADMIN_PASSWORD="your-strong-password"
$env:SECRET_KEY="any-random-string"

python .\app.py
```

Open `http://localhost:5000`

## Default login (if you don’t set env vars)

- Username: `admin`
- Password: `admin123`

## Make it public (simple options)

- **Render (recommended)**: deploy using `render.yaml` (included).
- **Railway / Fly.io**: deploy as a standard Python web service (use start command below).
- **DigitalOcean / VPS**: run behind a reverse proxy (nginx) with gunicorn.

### Deploy on Render (public URL)

1. Create a GitHub repo for this folder and push the code.
2. In Render: New → **Blueprint** → select your repo.
3. When it asks, set **ADMIN_PASSWORD** to a strong password.
4. Deploy. Render will give you a public URL like `https://...onrender.com`.

#### Important (Render Free tier)

Render’s **free tier does not support persistent disks**, so SQLite storage **may reset** on redeploy/restart.

**Best choice (free + persistent): Render + Neon Postgres**

1. Create a free Postgres on Neon.
2. Copy the connection string (it looks like `postgres://...`).
3. In Render → your service → **Environment** → add:
   - `DATABASE_URL` = (paste Neon connection string)
4. Redeploy.

If you *don’t* set `DATABASE_URL`, the app falls back to SQLite which may reset on Render free tier.

### Start command (for hosts that ask)

Use:

```bash
gunicorn wsgi:app --bind 0.0.0.0:$PORT
```

### Windows “production-like” run (optional)

`gunicorn` is for Linux hosting (Render). On Windows, you can use `waitress`:

```powershell
$env:PORT="5000"
.\.venv\Scripts\waitress-serve.exe --listen=0.0.0.0:$env:PORT wsgi:app
```

