"""
Background automation: appointment reminders and recall messages.

These are the two features that turn Recall from a booking form into
something worth a monthly subscription - a clinic can automate the
"remind them tomorrow" and "it's been 6 months, come back" messages that
otherwise depend on a receptionist remembering to do them by hand.

Both jobs are plain functions (not tied to APScheduler) so they can be
tested directly by calling them with a controlled database state, and
wired into a scheduler (see app/scheduler.py) for actual periodic runs.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Clinic, Appointment, Patient, ChatMessage
from app.chatbot.providers import get_provider
from app.chatbot.state import get_state, reset_state


def send_due_reminders(app):
    """
    For every clinic with reminders enabled, find confirmed appointments
    starting in roughly `reminder_hours_before` hours that haven't been
    reminded yet, and send a WhatsApp reminder.
    """
    with app.app_context():
        clinics = Clinic.query.filter_by(reminders_enabled=True).all()
        sent_count = 0

        for clinic in clinics:
            if not clinic.has_whatsapp_configured():
                continue

            window_start = clinic.local_now()
            window_end = window_start + timedelta(hours=1)
            target_start = window_start + timedelta(hours=clinic.reminder_hours_before)
            target_end = window_end + timedelta(hours=clinic.reminder_hours_before)

            due = (
                Appointment.query.filter_by(clinic_id=clinic.id, status=Appointment.STATUS_CONFIRMED)
                .filter(Appointment.reminder_sent_at.is_(None))
                .filter(Appointment.appointment_date >= target_start.date())
                .filter(Appointment.appointment_date <= target_end.date())
                .all()
            )

            provider = get_provider(clinic)
            for appt in due:
                appt_dt = datetime.combine(appt.appointment_date, appt.appointment_time)
                if not (target_start.replace(tzinfo=None) <= appt_dt <= target_end.replace(tzinfo=None)):
                    continue

                patient = appt.patient
                doctor_line = f" with Dr. {appt.doctor.name}" if appt.doctor else ""
                message = (
                    f"Reminder: you have an appointment at {clinic.clinic_name}{doctor_line} "
                    f"on {appt.appointment_date.strftime('%A, %d %B')} at "
                    f"{appt.appointment_time.strftime('%I:%M %p').lstrip('0')}.\n\n"
                    "Reply 'cancel' if you can't make it, so we can offer the slot to someone else."
                )
                provider.send_message(patient.phone, message)
                db.session.add(ChatMessage(
                    clinic_id=clinic.id, patient_phone=patient.phone,
                    message=message, sender_type=ChatMessage.SENDER_BOT,
                ))
                appt.reminder_sent_at = datetime.utcnow()
                sent_count += 1

            db.session.commit()

        return sent_count


def send_due_recalls(app):
    """
    For every clinic with recall enabled, find patients whose most recent
    completed appointment was exactly `recall_interval_days` ago (or more,
    and not yet recalled since), who have no upcoming booking, and send a
    "time to come back" message that drops them straight into the booking
    flow if they reply.
    """
    with app.app_context():
        clinics = Clinic.query.filter_by(recall_enabled=True).all()
        sent_count = 0

        for clinic in clinics:
            if not clinic.has_whatsapp_configured():
                continue

            cutoff = clinic.local_today() - timedelta(days=clinic.recall_interval_days)
            provider = get_provider(clinic)

            candidates = (
                db.session.query(Patient)
                .join(Appointment, Appointment.patient_id == Patient.id)
                .filter(Patient.clinic_id == clinic.id)
                .filter(Appointment.status == Appointment.STATUS_COMPLETED)
                .filter(Appointment.appointment_date <= cutoff)
                .distinct()
                .all()
            )

            for patient in candidates:
                last_completed = (
                    Appointment.query.filter_by(patient_id=patient.id, status=Appointment.STATUS_COMPLETED)
                    .order_by(Appointment.appointment_date.desc())
                    .first()
                )
                if not last_completed or last_completed.appointment_date > cutoff:
                    continue

                has_upcoming = Appointment.query.filter(
                    Appointment.patient_id == patient.id,
                    Appointment.status.in_([Appointment.STATUS_PENDING, Appointment.STATUS_CONFIRMED]),
                    Appointment.appointment_date >= clinic.local_today(),
                ).first()
                if has_upcoming:
                    continue

                already_recalled = (
                    patient.last_recall_sent_at
                    and patient.last_recall_sent_at.date() > last_completed.appointment_date
                )
                if already_recalled:
                    continue

                name_part = f", {patient.name.split()[0]}" if patient.name else ""
                message = (
                    f"Hi{name_part} — it's been a while since your last visit to {clinic.clinic_name}. "
                    "Time for a checkup? Reply 'menu' to book a slot that works for you."
                )
                provider.send_message(patient.phone, message)
                db.session.add(ChatMessage(
                    clinic_id=clinic.id, patient_phone=patient.phone,
                    message=message, sender_type=ChatMessage.SENDER_BOT,
                ))
                patient.last_recall_sent_at = datetime.utcnow()

                # Make sure their next reply lands on the menu, not stuck in
                # whatever step their conversation was in months ago.
                state = get_state(clinic.id, patient.phone)
                reset_state(state)

                sent_count += 1

            db.session.commit()

        return sent_count
