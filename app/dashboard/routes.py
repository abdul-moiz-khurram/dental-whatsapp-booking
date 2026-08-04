from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models import Appointment, Patient, Doctor, Clinic, ChatMessage, User, ConversationState
from app.auth.decorators import owner_required
from app.chatbot.providers import get_provider
from app.chatbot.state import get_state, reset_state

dashboard_bp = Blueprint("dashboard", __name__, template_folder="../templates/dashboard")


@dashboard_bp.route("/")
@login_required
def overview():
    clinic_id = current_user.clinic_id
    clinic = Clinic.query.get(clinic_id)
    today = date.today()

    base_query = Appointment.query.filter_by(clinic_id=clinic_id)
    if current_user.role == User.ROLE_DENTIST and current_user.doctor_id:
        base_query = base_query.filter_by(doctor_id=current_user.doctor_id)

    todays_appointments = (
        base_query.filter_by(appointment_date=today)
        .filter(Appointment.status != Appointment.STATUS_CANCELLED)
        .order_by(Appointment.appointment_time)
        .all()
    )
    upcoming_appointments = (
        base_query.filter(
            Appointment.appointment_date > today,
            Appointment.status != Appointment.STATUS_CANCELLED,
        )
        .order_by(Appointment.appointment_date, Appointment.appointment_time)
        .limit(8)
        .all()
    )
    pending_appointments = (
        base_query.filter_by(status=Appointment.STATUS_PENDING)
        .order_by(Appointment.appointment_date, Appointment.appointment_time)
        .limit(8)
        .all()
    )

    stats = {
        "today_count": len(todays_appointments),
        "pending_count": Appointment.query.filter_by(clinic_id=clinic_id, status=Appointment.STATUS_PENDING).count(),
        "patients_count": Patient.query.filter_by(clinic_id=clinic_id).count(),
        "doctors_count": Doctor.query.filter_by(clinic_id=clinic_id, active=True).count(),
    }

    # Business insights, shown only to owners - this is the "would a clinic
    # pay for this" view: is the schedule full, and are patients showing up.
    business_insights = None
    if current_user.is_owner():
        thirty_days_ago = today - timedelta(days=30)
        recent = Appointment.query.filter(
            Appointment.clinic_id == clinic_id,
            Appointment.appointment_date >= thirty_days_ago,
            Appointment.appointment_date <= today,
        ).all()
        completed = sum(1 for a in recent if a.status == Appointment.STATUS_COMPLETED)
        no_shows = sum(1 for a in recent if a.status == Appointment.STATUS_NO_SHOW)
        cancelled = sum(1 for a in recent if a.status == Appointment.STATUS_CANCELLED)
        denom = completed + no_shows
        business_insights = {
            "total_last_30d": len(recent),
            "completed": completed,
            "no_shows": no_shows,
            "cancelled": cancelled,
            "no_show_rate": round((no_shows / denom) * 100) if denom else None,
        }

    # Onboarding checklist for brand-new clinics - nothing here works until
    # a doctor exists and WhatsApp is connected, so make that obvious.
    checklist = {
        "has_doctor": Doctor.query.filter_by(clinic_id=clinic_id).count() > 0,
        "whatsapp_connected": clinic.has_whatsapp_configured(),
        "welcome_customized": bool(clinic.welcome_message) and "{clinic_name}" not in (clinic.welcome_message or ""),
    }
    show_checklist = not (checklist["has_doctor"] and checklist["whatsapp_connected"])

    return render_template(
        "dashboard/overview.html",
        todays_appointments=todays_appointments,
        upcoming_appointments=upcoming_appointments,
        pending_appointments=pending_appointments,
        stats=stats,
        business_insights=business_insights,
        checklist=checklist,
        show_checklist=show_checklist,
        is_dentist_view=(current_user.role == User.ROLE_DENTIST and current_user.doctor_id),
    )


@dashboard_bp.route("/patients")
@login_required
def patients():
    search = request.args.get("q", "").strip()
    query = Patient.query.filter_by(clinic_id=current_user.clinic_id)
    if search:
        query = query.filter(
            db.or_(Patient.name.ilike(f"%{search}%"), Patient.phone.ilike(f"%{search}%"))
        )
    all_patients = query.order_by(Patient.created_at.desc()).all()

    appt_counts = dict(
        db.session.query(Appointment.patient_id, func.count(Appointment.id))
        .filter(Appointment.clinic_id == current_user.clinic_id)
        .group_by(Appointment.patient_id)
        .all()
    )
    return render_template("dashboard/patients.html", patients=all_patients, appt_counts=appt_counts, search=search)


@dashboard_bp.route("/patients/<int:patient_id>")
@login_required
def patient_detail(patient_id):
    patient = Patient.query.filter_by(id=patient_id, clinic_id=current_user.clinic_id).first_or_404()
    history = (
        Appointment.query.filter_by(patient_id=patient.id)
        .order_by(Appointment.appointment_date.desc())
        .all()
    )
    return render_template("dashboard/patient_detail.html", patient=patient, history=history)


@dashboard_bp.route("/settings", methods=["GET", "POST"])
@login_required
@owner_required
def settings():
    clinic = Clinic.query.get(current_user.clinic_id)

    if request.method == "POST":
        section = request.form.get("section", "clinic")

        if section == "clinic":
            clinic.clinic_name = request.form.get("clinic_name", clinic.clinic_name).strip()
            clinic.owner_name = request.form.get("owner_name", clinic.owner_name).strip()
            clinic.phone = request.form.get("phone", "").strip()
            clinic.whatsapp_number = request.form.get("whatsapp_number", clinic.whatsapp_number).strip()
            clinic.address = request.form.get("address", "").strip()
            clinic.welcome_message = request.form.get("welcome_message", clinic.welcome_message)
            try:
                clinic.slot_duration_minutes = int(request.form.get("slot_duration_minutes", 30))
            except ValueError:
                pass
            flash("Clinic information saved.", "success")

        elif section == "whatsapp":
            clinic.whatsapp_provider = request.form.get("whatsapp_provider", "twilio")
            clinic.twilio_account_sid = request.form.get("twilio_account_sid", "").strip() or None
            clinic.twilio_whatsapp_from = request.form.get("twilio_whatsapp_from", "").strip() or None
            new_twilio_token = request.form.get("twilio_auth_token", "").strip()
            if new_twilio_token:
                clinic.set_twilio_auth_token(new_twilio_token)

            clinic.meta_phone_number_id = request.form.get("meta_phone_number_id", "").strip() or None
            clinic.meta_verify_token = request.form.get("meta_verify_token", "").strip() or None
            new_meta_token = request.form.get("meta_access_token", "").strip()
            if new_meta_token:
                clinic.set_meta_access_token(new_meta_token)

            flash("WhatsApp integration saved.", "success")

        elif section == "knowledge":
            clinic.opening_hours_text = request.form.get("opening_hours_text", "").strip()
            clinic.insurance_text = request.form.get("insurance_text", "").strip()
            clinic.pricing_text = request.form.get("pricing_text", "").strip()
            clinic.treatments_text = request.form.get("treatments_text", "").strip()
            clinic.aftercare_text = request.form.get("aftercare_text", "").strip()
            clinic.first_time_text = request.form.get("first_time_text", "").strip()
            clinic.emergency_instructions = request.form.get("emergency_instructions", "").strip()
            flash("Chatbot knowledge base saved.", "success")

        elif section == "automation":
            clinic.reminders_enabled = bool(request.form.get("reminders_enabled"))
            clinic.recall_enabled = bool(request.form.get("recall_enabled"))
            try:
                clinic.reminder_hours_before = max(1, int(request.form.get("reminder_hours_before", 24)))
            except ValueError:
                pass
            try:
                clinic.recall_interval_days = max(1, int(request.form.get("recall_interval_days", 180)))
            except ValueError:
                pass
            flash("Automation settings saved.", "success")

        db.session.commit()
        return redirect(url_for("dashboard.settings"))

    return render_template("dashboard/settings.html", clinic=clinic)


@dashboard_bp.route("/team")
@login_required
@owner_required
def team():
    members = User.query.filter_by(clinic_id=current_user.clinic_id).order_by(User.created_at).all()
    doctors = Doctor.query.filter_by(clinic_id=current_user.clinic_id).order_by(Doctor.name).all()
    return render_template("dashboard/team.html", members=members, doctors=doctors)


@dashboard_bp.route("/team/add", methods=["POST"])
@login_required
@owner_required
def team_add():
    from app.email_utils import send_email

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", User.ROLE_STAFF)
    password = request.form.get("password", "")
    doctor_id = request.form.get("doctor_id") or None

    errors = []
    if not username:
        errors.append("Username is required.")
    if User.query.filter_by(username=username).first():
        errors.append("That username is already taken.")
    if not email or "@" not in email:
        errors.append("A valid email is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if role not in (User.ROLE_STAFF, User.ROLE_DENTIST):
        errors.append("Invalid role.")

    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("dashboard.team"))

    member = User(
        clinic_id=current_user.clinic_id,
        username=username,
        email=email,
        role=role,
        doctor_id=int(doctor_id) if (role == User.ROLE_DENTIST and doctor_id) else None,
    )
    member.set_password(password)
    db.session.add(member)
    db.session.commit()

    send_email(
        to=email,
        subject="You've been added to Recall",
        body=(
            f"Hi {username},\n\n"
            f"You've been added as a {role} on your clinic's Recall dashboard.\n"
            f"Sign in with username '{username}' and the password you were given, "
            "then change it from your account if you'd like.\n\n- Recall"
        ),
    )
    flash(f"{username} has been added.", "success")
    return redirect(url_for("dashboard.team"))


@dashboard_bp.route("/team/<int:user_id>/toggle", methods=["POST"])
@login_required
@owner_required
def team_toggle(user_id):
    member = User.query.filter_by(id=user_id, clinic_id=current_user.clinic_id).first_or_404()
    if member.id == current_user.id:
        flash("You can't deactivate your own account.", "error")
        return redirect(url_for("dashboard.team"))
    member.is_active_staff = not member.is_active_staff
    db.session.commit()
    return redirect(url_for("dashboard.team"))


@dashboard_bp.route("/reports")
@login_required
@owner_required
def reports():
    clinic_id = current_user.clinic_id
    today = date.today()
    start = today - timedelta(days=29)

    appointments = Appointment.query.filter(
        Appointment.clinic_id == clinic_id,
        Appointment.appointment_date >= start,
        Appointment.appointment_date <= today,
    ).all()

    by_day = {}
    for i in range(30):
        d = start + timedelta(days=i)
        by_day[d] = 0
    for a in appointments:
        if a.appointment_date in by_day:
            by_day[a.appointment_date] += 1

    completed = sum(1 for a in appointments if a.status == Appointment.STATUS_COMPLETED)
    no_shows = sum(1 for a in appointments if a.status == Appointment.STATUS_NO_SHOW)
    cancelled = sum(1 for a in appointments if a.status == Appointment.STATUS_CANCELLED)
    pending = sum(1 for a in appointments if a.status == Appointment.STATUS_PENDING)
    confirmed = sum(1 for a in appointments if a.status == Appointment.STATUS_CONFIRMED)
    denom = completed + no_shows

    doctor_counts = {}
    for a in appointments:
        key = a.doctor.name if a.doctor else "No preference"
        doctor_counts[key] = doctor_counts.get(key, 0) + 1

    return render_template(
        "dashboard/reports.html",
        by_day=sorted(by_day.items()),
        total=len(appointments),
        completed=completed,
        no_shows=no_shows,
        cancelled=cancelled,
        pending=pending,
        confirmed=confirmed,
        no_show_rate=round((no_shows / denom) * 100) if denom else None,
        doctor_counts=sorted(doctor_counts.items(), key=lambda kv: -kv[1]),
    )


@dashboard_bp.route("/conversations")
@login_required
def conversations():
    """A log of recent chatbot conversations, grouped by patient, with a
    manual-reply box and human-takeover toggle for each thread."""
    recent = (
        ChatMessage.query.filter_by(clinic_id=current_user.clinic_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(300)
        .all()
    )
    grouped = {}
    for msg in recent:
        grouped.setdefault(msg.patient_phone, []).append(msg)
    for phone in grouped:
        grouped[phone].reverse()

    takeover_state = {}
    for phone in grouped:
        state = ConversationState.query.filter_by(clinic_id=current_user.clinic_id, patient_phone=phone).first()
        takeover_state[phone] = bool(state and state.human_takeover)

    return render_template("dashboard/conversations.html", grouped=grouped, takeover_state=takeover_state)


@dashboard_bp.route("/conversations/<path:phone>/takeover", methods=["POST"])
@login_required
def take_over_conversation(phone):
    state = get_state(current_user.clinic_id, phone)
    state.human_takeover = True
    db.session.commit()
    flash(f"You're now handling {phone} manually - the bot will stay quiet on this thread.", "info")
    return redirect(url_for("dashboard.conversations"))


@dashboard_bp.route("/conversations/<path:phone>/return-to-bot", methods=["POST"])
@login_required
def return_to_bot(phone):
    state = get_state(current_user.clinic_id, phone)
    state.human_takeover = False
    db.session.commit()
    flash(f"The bot is back in control of {phone}.", "info")
    return redirect(url_for("dashboard.conversations"))


@dashboard_bp.route("/conversations/<path:phone>/reply", methods=["POST"])
@login_required
def reply_to_patient(phone):
    from app.models import ChatMessage as CM

    body = request.form.get("message", "").strip()
    if not body:
        return redirect(url_for("dashboard.conversations"))

    clinic = Clinic.query.get(current_user.clinic_id)
    provider = get_provider(clinic)
    provider.send_message(phone, body)

    db.session.add(CM(clinic_id=clinic.id, patient_phone=phone, message=body, sender_type=CM.SENDER_STAFF))
    db.session.commit()
    flash("Message sent.", "success")
    return redirect(url_for("dashboard.conversations"))
