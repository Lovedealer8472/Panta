# Pantanakerfi

Lightweight Flask + SQLite order board used by Tölvuhvíslarinn ehf.,
served at `https://pantanakerfi.tolvuhvislarinn.is/`.

## Stack

- Flask 3.x, Werkzeug, waitress (production WSGI)
- SQLite (`pantanakerfi.db`, single file in app root)
- Vanilla HTML/CSS templates in `templates/` and `static/`

## Run locally

```bash
python -m venv venv
. venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # then edit SECRET_KEY / ADMIN_PASSWORD_HASH
python app.py
```

Default URL: `http://127.0.0.1:5000`.

To generate an admin password hash:

```python
from werkzeug.security import generate_password_hash
print(generate_password_hash("your-password"))
```

## Production layout (edge box)

- App dir: `/opt/pantanakerfi/`
- Service: `pantanakerfi.service` (systemd, runs `venv/bin/python app.py`)
- Reverse proxy: Nginx vhost on `pantanakerfi.tolvuhvislarinn.is`
- Backups: copy `pantanakerfi.db` (and `uploads/` once attachments are in use)

## Files NOT in this repo

`.env`, `pantanakerfi.db`, `venv/`, `uploads/` are runtime / secrets and
stay on the server. `.gitignore` keeps them out.
