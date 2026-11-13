# CampusFix

CampusFix is a small Flask application for a VTU CSE DevOps project. Students submit campus complaints, and an administrator updates each complaint from Pending to In Progress or Resolved. Complaints are stored in SQLite.

## Features

- Home page with a complaint form and a dashboard of every complaint
- Complaint title, description, and category
- Categories: Wi-Fi, Classroom, Laboratory, Infrastructure, and Other
- Status values: Pending, In Progress, and Resolved
- Admin sign-in and an admin dashboard that updates status
- Input validation and parameterized SQL
- `/health` returns `{"status":"healthy"}`

## Security

- SQL uses `?` placeholders. Category and status filters are allow-listed before they are added to a query.
- The admin password is read from the environment, hashed with Werkzeug at startup, and checked with `check_password_hash`. It is not stored in SQLite.
- Admin updates require a signed-in session. The session cookie is HTTP-only.
- Forms that change data require a CSRF token stored in the session.
- The development server binds to `127.0.0.1`.

The admin username is `admin`.

## Local development defaults

If the variables below are missing or empty, CampusFix starts with defaults so you can run it on your own computer:

| Setting | Variable | Local default |
| --- | --- | --- |
| Flask secret key | `CAMPUSFIX_SECRET_KEY` | `campusfix-local-dev-secret-change-me` |
| Admin password | `CAMPUSFIX_ADMIN_PASSWORD` | `campusfix-dev` |

These defaults are for local testing only. The password and secret are in the source code, so anyone who can open the app can sign in as admin until you replace them. A yellow banner is shown while either default is in use. Do not use them on a shared or public server.

Set a long random secret and a password before you share the app. For HTTPS deployments, also set `CAMPUSFIX_COOKIE_SECURE=1`.

## Run the application

From the project folder in PowerShell:

```powershell
cd C:\Users\91636\CampusFix\CampusFix
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:CAMPUSFIX_SECRET_KEY = "replace-with-a-long-random-string"
$env:CAMPUSFIX_ADMIN_PASSWORD = "choose-a-strong-password"
python app.py
```

If activation is blocked, run the venv Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000

- Home and public dashboard: http://127.0.0.1:5000
- Admin: http://127.0.0.1:5000/admin
- Health: http://127.0.0.1:5000/health

Sign in with username `admin` and the password in `CAMPUSFIX_ADMIN_PASSWORD`. If you skipped that variable, the local password is `campusfix-dev`.

The database file is `instance/campusfix.db`. Delete that file to clear every complaint, then start the app again.

To run without the venv activation step on a machine that already has Flask installed, `python app.py` from this folder is enough.

## Test it by hand

1. Open http://127.0.0.1:5000 and confirm the home page, the four totals, and the empty dashboard.
2. Submit a complaint with a title, a description of at least 10 characters, and a category such as Laboratory. It appears as Pending with a reference like CF-001.
3. Submit a title shorter than 3 characters. The page shows a validation error and does not add a row.
4. Open http://127.0.0.1:5000/admin. Status controls are not shown before sign-in.
5. Sign in with a wrong password and confirm the error. Sign in with username `admin` and the configured password.
6. Change the complaint to In Progress, then Resolved. Return to the home dashboard and confirm the badge and totals.
7. Log out and confirm the admin page asks you to sign in again.
8. Open http://127.0.0.1:5000/health and confirm the JSON body is `{"status":"healthy"}`.

## Automated tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests use a temporary SQLite file. They cover the health check, validation, persistence, filters, CSRF rejection, admin sign-in, status updates, logout, and the environment-variable password.

## Project layout

```
app.py
requirements.txt
README.md
static/style.css
templates/base.html
templates/index.html
templates/admin.html
tests/test_app.py
instance/campusfix.db    created on first run
```
