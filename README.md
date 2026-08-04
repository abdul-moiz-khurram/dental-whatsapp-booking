# Recall — WhatsApp Appointment Booking for Dental Clinics

A focused product: patients book dental appointments over WhatsApp, automatically.
Clinic staff manage everything from a simple dashboard. This is **not** a full
practice-management suite — no billing, no medical records, no complex roles.

---

## 1. What's included

```
dental-whatsapp-booking/
├── app/
│   ├── auth/            # Login / logout (Flask-Login)
│   ├── dashboard/       # Overview, patients, settings, conversation log
│   ├── chatbot/         # Conversation engine + WhatsApp provider layer
│   │   ├── providers/   # base.py, twilio_provider.py, meta_provider.py
│   │   ├── engine.py    # The booking state machine
│   │   ├── state.py     # Per-patient conversation state persistence
│   │   └── routes.py    # /webhook/whatsapp
│   ├── appointments/    # Availability logic + dashboard CRUD
│   ├── doctors/         # Doctor schedules
│   ├── models.py        # clinics, doctors, patients, appointments,
│   │                       chat_messages, users, conversation_states
│   ├── config.py
│   ├── templates/       # Jinja templates (landing, auth, dashboard)
│   └── static/          # CSS/JS for the landing page + dashboard
├── run.py               # App entry point
├── seed.py              # Creates the first clinic + owner login
├── requirements.txt
└── .env.example
```

## 2. Local setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set SECRET_KEY, and later your WhatsApp provider credentials

python seed.py                  # creates instance/recall.db + a demo clinic
python run.py                   # runs on http://localhost:5000
```

Sign in at `/auth/login` with:
- **username:** `admin`
- **password:** `changeme123` (change this immediately — see "Change the admin password" below)

The landing page is at `/`. The dashboard is at `/dashboard`.

## 3. Switching to Postgres (recommended for a real install)

1. Create a database: `createdb recall`
2. In `.env`, set:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/recall
   ```
3. Run `python seed.py` again (it calls `db.create_all()` and seeds the first clinic).

For schema changes going forward, Flask-Migrate is already wired up:
```bash
flask --app run.py db init      # first time only
flask --app run.py db migrate -m "message"
flask --app run.py db upgrade
```

## 4. Connecting a real WhatsApp number

Set `WHATSAPP_PROVIDER=twilio` or `WHATSAPP_PROVIDER=meta` in `.env`.

### Option A — Twilio WhatsApp API (fastest to test with)
1. Create a Twilio account and activate the WhatsApp Sandbox (or a production
   WhatsApp sender once approved).
2. In `.env`, set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`.
3. In the Twilio console, set the WhatsApp Sandbox/Sender's **"When a message
   comes in"** webhook to:
   ```
   https://your-domain.com/webhook/whatsapp
   ```
   Method: `POST`.
4. Message the Twilio sandbox number with "Hi" to test the live flow.

### Option B — Meta WhatsApp Cloud API (official Business API)
1. Create a Meta App with the WhatsApp product, get a phone number ID and
   access token.
2. In `.env`, set `META_PHONE_NUMBER_ID`, `META_ACCESS_TOKEN`, `META_VERIFY_TOKEN`.
3. In the Meta App dashboard, register the webhook URL:
   ```
   https://your-domain.com/webhook/whatsapp
   ```
   Meta will send a one-time GET verification request; the app already
   handles this using `META_VERIFY_TOKEN`.
4. Subscribe the webhook to the `messages` field.

Either provider can be swapped without touching `engine.py`, `models.py`, or
any dashboard code — that's the entire point of the `providers/` layer.

## 5. Multi-clinic note

Each row in `clinics` has its own `whatsapp_number`. If you ever sell this to
more than one clinic on the same deployment, the webhook looks up the clinic
by the WhatsApp number the patient messaged. For a typical single-clinic
install, just seed one clinic and this resolves automatically.

## 6. Change the admin password

There's no self-service "forgot password" flow by design (this is a small,
low-maintenance install, not a multi-tenant SaaS with email infra). To set a
real password:

```bash
python -c "
from app import create_app
from app.extensions import db
from app.models import User
app = create_app()
with app.app_context():
    u = User.query.filter_by(username='admin').first()
    u.set_password('your-new-strong-password')
    db.session.commit()
"
```

## 7. Deployment

For a simple VPS deployment:

```bash
pip install -r requirements.txt
gunicorn -w 4 -b 0.0.0.0:8000 run:app
```

Put this behind Nginx with TLS (WhatsApp providers require HTTPS webhooks).
Set `FLASK_ENV=production` in `.env` and make sure `SECRET_KEY` is a long
random string, not the default.

## 8. What this product intentionally does NOT do

- No billing, invoicing, or payments
- No clinical/medical records
- No complex role/permission system
- No treatment charting

If a clinic asks for these, that's a different (larger) product — keeping
this one focused is what makes it fast to install and easy to sell.
