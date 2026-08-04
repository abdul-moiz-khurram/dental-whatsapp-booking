"""
Database models.

Deliberately small and focused: this product books appointments over
WhatsApp for a single clinic (or a handful of clinics if a reseller runs
several installs). It is NOT a clinical records system, so there is no
treatment history, billing, or charting data here on purpose.
"""
from datetime import datetime, date, time

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


class Clinic(db.Model):
    __tablename__ = "clinics"

    id = db.Column(db.Integer, primary_key=True)
    clinic_name = db.Column(db.String(120), nullable=False)
    owner_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(32))
    whatsapp_number = db.Column(db.String(32), unique=True, nullable=False)
    address = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Optional chatbot personalization, editable from the dashboard.
    welcome_message = db.Column(
        db.Text,
        default="Welcome to {clinic_name}.\nHow can we help you today?",
    )
    timezone = db.Column(db.String(64), default="UTC")
    slot_duration_minutes = db.Column(db.Integer, default=30)

    # --- Reminder / recall automation (the product's namesake feature) --
    reminders_enabled = db.Column(db.Boolean, default=True)
    reminder_hours_before = db.Column(db.Integer, default=24)
    recall_enabled = db.Column(db.Boolean, default=True)
    recall_interval_days = db.Column(db.Integer, default=180)  # ~6 months

    # --- Per-clinic WhatsApp credentials --------------------------------
    # Each clinic connects its own WhatsApp number/provider from Settings,
    # instead of the whole server sharing one global provider. Secrets are
    # encrypted at rest (see app/security.py) and only decrypted right
    # before an outbound API call. If these are blank, the app falls back
    # to the server-wide Config values (see chatbot/providers/__init__.py)
    # so existing single-clinic installs keep working unchanged.
    whatsapp_provider = db.Column(db.String(20), default="twilio")  # "twilio" or "meta"
    twilio_account_sid = db.Column(db.String(255))
    twilio_auth_token_encrypted = db.Column(db.Text)
    twilio_whatsapp_from = db.Column(db.String(64))
    meta_phone_number_id = db.Column(db.String(64))
    meta_access_token_encrypted = db.Column(db.Text)
    meta_verify_token = db.Column(db.String(120))

    # --- Chatbot knowledge base, used by the FAQ/emergency triage layer -
    # Plain-language answers the clinic writes once from Settings. If a
    # field is left blank, the bot tells the patient to contact the clinic
    # directly rather than guessing - it never invents an answer.
    opening_hours_text = db.Column(db.Text)
    insurance_text = db.Column(db.Text)
    pricing_text = db.Column(db.Text)
    treatments_text = db.Column(db.Text)
    aftercare_text = db.Column(db.Text)
    first_time_text = db.Column(db.Text)
    emergency_instructions = db.Column(db.Text)

    doctors = db.relationship("Doctor", backref="clinic", lazy=True, cascade="all, delete-orphan")
    patients = db.relationship("Patient", backref="clinic", lazy=True, cascade="all, delete-orphan")
    appointments = db.relationship("Appointment", backref="clinic", lazy=True, cascade="all, delete-orphan")
    users = db.relationship("User", backref="clinic", lazy=True, cascade="all, delete-orphan")

    def get_twilio_auth_token(self):
        from app.security import decrypt_value
        return decrypt_value(self.twilio_auth_token_encrypted)

    def set_twilio_auth_token(self, raw_value):
        from app.security import encrypt_value
        self.twilio_auth_token_encrypted = encrypt_value(raw_value) if raw_value else None

    def get_meta_access_token(self):
        from app.security import decrypt_value
        return decrypt_value(self.meta_access_token_encrypted)

    def set_meta_access_token(self, raw_value):
        from app.security import encrypt_value
        self.meta_access_token_encrypted = encrypt_value(raw_value) if raw_value else None

    def has_whatsapp_configured(self) -> bool:
        if self.whatsapp_provider == "meta":
            return bool(self.meta_phone_number_id and self.meta_access_token_encrypted)
        return bool(self.twilio_account_sid and self.twilio_auth_token_encrypted and self.twilio_whatsapp_from)

    def local_now(self):
        """
        Current date/time in this clinic's own timezone, not the server's.
        Falls back to naive UTC-ish server time if the stored timezone name
        is missing or invalid, so this never raises for existing data.
        """
        from datetime import datetime as _dt
        try:
            from zoneinfo import ZoneInfo
            return _dt.now(ZoneInfo(self.timezone or "UTC"))
        except Exception:
            return _dt.utcnow()

    def local_today(self):
        return self.local_now().date()


class Doctor(db.Model):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    specialization = db.Column(db.String(120))
    # Stored as comma-separated day codes, e.g. "mon,tue,wed,thu,fri"
    available_days = db.Column(db.String(64), default="mon,tue,wed,thu,fri")
    # Stored as "HH:MM-HH:MM", e.g. "09:00-17:00"
    available_times = db.Column(db.String(32), default="09:00-17:00")
    active = db.Column(db.Boolean, default=True)

    appointments = db.relationship("Appointment", backref="doctor", lazy=True)

    def working_day_codes(self):
        return [d.strip() for d in (self.available_days or "").split(",") if d.strip()]

    def working_hours(self):
        try:
            start_s, end_s = (self.available_times or "09:00-17:00").split("-")
            h1, m1 = [int(x) for x in start_s.split(":")]
            h2, m2 = [int(x) for x in end_s.split(":")]
            return time(h1, m1), time(h2, m2)
        except Exception:
            return time(9, 0), time(17, 0)


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False)
    name = db.Column(db.String(120))
    phone = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_recall_sent_at = db.Column(db.DateTime, nullable=True)

    appointments = db.relationship("Appointment", backref="patient", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("clinic_id", "phone", name="uq_patient_clinic_phone"),
    )


class Appointment(db.Model):
    __tablename__ = "appointments"

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"
    STATUS_COMPLETED = "completed"
    STATUS_NO_SHOW = "no_show"

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=True)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.Time, nullable=False)
    reason = db.Column(db.String(255))
    status = db.Column(db.String(20), default=STATUS_PENDING)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reminder_sent_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        # Prevents two patients from both booking the same doctor's slot in
        # the small race window between the chatbot's availability check and
        # the insert. Scoped to active (non-cancelled) appointments so a
        # cancelled slot can always be rebooked. Postgres-only (SQLite, our
        # documented dev-only database, doesn't support this cleanly) - see
        # README "Switching to Postgres".
        db.Index(
            "uq_active_doctor_slot",
            "clinic_id", "doctor_id", "appointment_date", "appointment_time",
            unique=True,
            postgresql_where=db.text("status != 'cancelled' AND doctor_id IS NOT NULL"),
        ),
    )

    def as_display_dict(self):
        return {
            "id": self.id,
            "patient": self.patient.name or self.patient.phone,
            "doctor": self.doctor.name if self.doctor else "No preference",
            "date": self.appointment_date.strftime("%A, %d %B"),
            "time": self.appointment_time.strftime("%I:%M %p").lstrip("0"),
            "status": self.status,
            "reason": self.reason or "-",
        }


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    SENDER_PATIENT = "patient"
    SENDER_BOT = "bot"
    SENDER_STAFF = "staff"

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=True)
    patient_phone = db.Column(db.String(32), nullable=False)
    message = db.Column(db.Text)
    sender_type = db.Column(db.String(16), default=SENDER_PATIENT)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    ROLE_OWNER = "owner"
    ROLE_STAFF = "staff"      # front-desk / receptionist
    ROLE_DENTIST = "dentist"  # a doctor who wants their own dashboard view

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default=ROLE_OWNER)
    # If this login represents a specific dentist, link it so their
    # dashboard can default to "their" schedule instead of the whole clinic.
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=True)
    is_active_staff = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    doctor_profile = db.relationship("Doctor", foreign_keys=[doctor_id])

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_active(self):
        # Overrides Flask-Login's UserMixin default so a deactivated staff
        # account is immediately logged out / can't log back in.
        return self.is_active_staff

    def is_owner(self):
        return self.role == User.ROLE_OWNER


class ConversationState(db.Model):
    """
    Tracks where a patient is inside the booking conversation so the chatbot
    engine can resume statelessly across incoming webhook requests.
    """
    __tablename__ = "conversation_states"

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey("clinics.id"), nullable=False)
    patient_phone = db.Column(db.String(32), nullable=False)
    step = db.Column(db.String(40), default="menu")
    # JSON-serialized scratch data collected mid-conversation (name, date, etc.)
    data = db.Column(db.Text, default="{}")
    # When true, the chatbot stops auto-replying to this patient and staff
    # respond manually from the Conversations page instead. Toggled from
    # the dashboard - see dashboard.take_over_conversation / return_to_bot.
    human_takeover = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("clinic_id", "patient_phone", name="uq_conv_clinic_phone"),
    )
