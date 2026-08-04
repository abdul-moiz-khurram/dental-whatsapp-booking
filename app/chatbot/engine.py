"""
The conversation engine.

This is a small, explicit state machine rather than a generic NLP layer on
purpose: dental patients booking on WhatsApp need predictable, fast replies,
not an open-ended chat. Every step has one job and a clear way to bail back
to the main menu by sending "menu" or "cancel".
"""
import re
from datetime import datetime, date, time, timedelta

from app.extensions import db
from app.models import Doctor, Appointment, ChatMessage
from app.chatbot.state import get_state, save_state, reset_state, get_data
from app.appointments.services import (
    get_available_slots,
    is_slot_available,
    find_or_create_patient,
    book_appointment,
)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

EXIT_WORDS = {"menu", "cancel", "back", "restart"}
GREETING_WORDS = {"hi", "hello", "hey", "salam", "assalamualaikum", "asalam o alaikum", "start", "hie", "helo"}

# Emergency language always gets a prefix reminding the patient to call the
# clinic directly - checked on every message, at any step, without ever
# interrupting or resetting whatever they were already doing (booking a
# routine cleaning shouldn't get derailed just because "hurts" appears in a
# sentence like "my tooth hurts a little when I eat sugar").
EMERGENCY_KEYWORDS = [
    "severe pain", "unbearable", "excruciating", "swelling", "swollen",
    "bleeding a lot", "wont stop bleeding", "knocked out",
    "emergency", "cant stop the bleeding", "broke my tooth", "broken tooth",
    "chipped a tooth", "chipped my tooth", "face is swollen", "lot of pain",
]

# FAQ intents only interrupt the *menu* step (before a booking has started) -
# this is deliberate: mid-booking, whatever the patient types is answering
# the question we just asked them (their name, a date, a reason), and
# reinterpreting it as an FAQ lookup would silently break the booking flow.
# The brief's example questions ("what are your hours", "do you take
# insurance") are realistically asked before or between bookings, not while
# answering "what's your full name?".
FAQ_INTENTS = [
    ("opening_hours_text", ["hour", "hours", "open", "opening", "closing", "close", "timing"]),
    ("insurance_text", ["insurance", "covered", "coverage"]),
    ("pricing_text", ["price", "prices", "pricing", "cost", "how much", "fee", "fees", "charge"]),
    ("aftercare_text", ["aftercare", "after care", "after extraction", "after surgery", "after procedure", "can i eat", "eat after"]),
    ("treatments_text", ["treatment", "treatments", "braces", "whitening", "root canal", "extraction", "filling", "service", "services", "procedure"]),
    ("first_time_text", ["first time", "never visited", "never been", "new patient", "first visit"]),
]


def log_message(clinic_id, phone, message, sender_type):
    db.session.add(ChatMessage(
        clinic_id=clinic_id, patient_phone=phone, message=message, sender_type=sender_type
    ))
    db.session.commit()


def handle_incoming_message(clinic, phone: str, body: str) -> str:
    """
    Main entry point: takes the raw incoming text, returns the reply text -
    or None if a staff member has taken this specific conversation over
    manually (the bot logs the message but stays silent so it doesn't talk
    over a human).
    """
    body = (body or "").strip()
    log_message(clinic.id, phone, body, ChatMessage.SENDER_PATIENT)

    state = get_state(clinic.id, phone)

    if state.human_takeover:
        # Staff are handling this thread from the Conversations page - the
        # bot never auto-replies until they hand it back.
        return None

    data = get_data(state)
    lowered = body.lower()

    emergency_prefix = _check_emergency(clinic, lowered)

    if lowered in EXIT_WORDS or (state.step == "menu" and lowered in GREETING_WORDS):
        reset_state(state)
        reply = _menu_text(clinic)
        reply = f"{emergency_prefix}\n\n{reply}" if emergency_prefix else reply
        log_message(clinic.id, phone, reply, ChatMessage.SENDER_BOT)
        return reply

    # FAQ answers only interrupt the top-level menu - see FAQ_INTENTS comment
    # above for why this doesn't apply mid-booking.
    if state.step == "menu":
        faq_reply = _check_faq(clinic, lowered)
        if faq_reply:
            reply = f"{emergency_prefix}\n\n{faq_reply}" if emergency_prefix else faq_reply
            log_message(clinic.id, phone, reply, ChatMessage.SENDER_BOT)
            return reply

    handler = _STEP_HANDLERS.get(state.step, _handle_menu)
    reply = handler(clinic, phone, state, data, body)

    if emergency_prefix:
        reply = reply.replace("Sorry, I didn't catch that.\n\n", "")
        reply = f"{emergency_prefix}\n\n{reply}"

    log_message(clinic.id, phone, reply, ChatMessage.SENDER_BOT)
    return reply


def _check_emergency(clinic, lowered: str):
    words = set(re.findall(r"[a-z]+", lowered.replace("'", "")))
    matched = any(
        set(phrase.split()).issubset(words) for phrase in EMERGENCY_KEYWORDS
    )
    if not matched:
        return None

    if clinic.emergency_instructions:
        return clinic.emergency_instructions
    if clinic.phone:
        return f"That sounds urgent - please call {clinic.clinic_name} directly at {clinic.phone} right away."
    return f"That sounds urgent - please contact {clinic.clinic_name} directly as soon as possible."


def _check_faq(clinic, lowered: str):
    for field_name, keywords in FAQ_INTENTS:
        if any(kw in lowered for kw in keywords):
            answer = getattr(clinic, field_name, None)
            if answer:
                return f"{answer}\n\nReply 'menu' for booking options, or ask anything else."
            # We never invent an answer - if the clinic hasn't filled this
            # field in from Settings, we say so and point to a human.
            phone_line = f" at {clinic.phone}" if clinic.phone else ""
            return (
                f"I don't have that information yet - please contact {clinic.clinic_name}{phone_line} directly "
                "and our team can help.\n\nReply 'menu' for booking options."
            )
    return None


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

def _menu_text(clinic):
    welcome = (clinic.welcome_message or "Welcome to {clinic_name}.\nHow can we help you today?").format(
        clinic_name=clinic.clinic_name
    )
    return (
        f"{welcome}\n\n"
        "1. Book an appointment\n"
        "2. View available timings\n"
        "3. Contact clinic"
    )


def _handle_menu(clinic, phone, state, data, body):
    choice = body.strip()

    if choice in ("1", "book", "book an appointment"):
        save_state(state, "booking_name", {})
        return "Great - let's get you booked in.\n\nWhat's your full name?"

    if choice in ("2", "timings", "view available timings"):
        save_state(state, "timings_date", {})
        return "Which date would you like to check? (e.g. 15 January, or 'tomorrow')"

    if choice in ("3", "contact", "contact clinic"):
        save_state(state, "menu", {})
        phone_line = f"\nCall us: {clinic.phone}" if clinic.phone else ""
        address_line = f"\nAddress: {clinic.address}" if clinic.address else ""
        return f"{clinic.clinic_name}{phone_line}{address_line}\n\nSend 'menu' anytime to come back here."

    return "Sorry, I didn't catch that.\n\n" + _menu_text(clinic)


# ---------------------------------------------------------------------------
# Booking flow: name -> phone confirm -> date -> time -> doctor -> reason -> confirm
# ---------------------------------------------------------------------------

def _handle_booking_name(clinic, phone, state, data, body):
    if len(body.strip()) < 2:
        return "That doesn't look like a full name - could you type it again?"
    data["name"] = body.strip().title()
    save_state(state, "booking_phone", data)
    return f"Thanks, {data['name'].split()[0]}. What's the best phone number to reach you on for this appointment?"


def _handle_booking_phone(clinic, phone, state, data, body):
    digits = re.sub(r"[^\d+]", "", body)
    if len(digits) < 7:
        return "That phone number looks too short - please send it again (e.g. 03001234567)."
    data["contact_phone"] = digits
    save_state(state, "booking_date", data)
    return "What date works for you? (e.g. 15 January, tomorrow, or Monday)"


def _handle_booking_date(clinic, phone, state, data, body):
    today = clinic.local_today()
    parsed = parse_natural_date(body, today=today)
    if not parsed:
        return "I couldn't understand that date. Try a format like '15 January' or 'tomorrow'."

    if parsed < today:
        return "That date has already passed - please send a future date."

    data["date"] = parsed.isoformat()
    save_state(state, "booking_doctor", data)

    doctors = Doctor.query.filter_by(clinic_id=clinic.id, active=True).order_by(Doctor.name).all()
    if not doctors:
        save_state(state, "booking_time", data)
        return _prompt_for_time(clinic, data)

    listing = "\n".join(f"{i + 1}. Dr. {d.name} ({d.specialization or 'General Dentist'})" for i, d in enumerate(doctors))
    return (
        "Do you have a doctor preference? Reply with a number, or send "
        f"'no preference'.\n\n{listing}"
    )


def _handle_booking_doctor(clinic, phone, state, data, body):
    lowered = body.strip().lower()
    doctors = Doctor.query.filter_by(clinic_id=clinic.id, active=True).order_by(Doctor.name).all()

    if lowered in ("no preference", "no", "any", "0", "skip"):
        data["doctor_id"] = None
    else:
        try:
            idx = int(lowered) - 1
            data["doctor_id"] = doctors[idx].id
        except (ValueError, IndexError):
            return "Please reply with one of the listed numbers, or 'no preference'."

    save_state(state, "booking_time", data)
    return _prompt_for_time(clinic, data)


def _prompt_for_time(clinic, data):
    on_date = date.fromisoformat(data["date"])
    doctor = Doctor.query.get(data["doctor_id"]) if data.get("doctor_id") else None
    slots = get_available_slots(clinic, on_date, doctor=doctor, limit=6)

    if not slots:
        return _suggest_alternative_dates(clinic, on_date, doctor)

    lines = [f"- {t.strftime('%I:%M %p').lstrip('0')}" + (f" (Dr. {d.name})" if doctor is None else "") for d, t in slots]
    date_label = on_date.strftime("%A, %d %B")
    return (
        f"Here's what's open on {date_label}:\n\n" + "\n".join(lines) +
        "\n\nReply with a time (e.g. 4:00 PM)."
    )


def _suggest_alternative_dates(clinic, on_date, doctor):
    for offset in range(1, 8):
        alt_date = on_date + timedelta(days=offset)
        slots = get_available_slots(clinic, alt_date, doctor=doctor, limit=3)
        if slots:
            lines = [f"- {t.strftime('%I:%M %p').lstrip('0')}" for _, t in slots]
            return (
                f"Sorry, we're fully booked on {on_date.strftime('%A, %d %B')}.\n\n"
                f"The next available day is {alt_date.strftime('%A, %d %B')}:\n" + "\n".join(lines) +
                "\n\nWould you like one of these? Reply with a time, or send 'menu' to start over."
            )
    return "Sorry, we don't have any openings in the next week. Please send 'menu' and try 'Contact clinic' to call us directly."


def _handle_booking_time(clinic, phone, state, data, body):
    parsed_time = parse_natural_time(body)
    if not parsed_time:
        return "I couldn't understand that time. Try a format like '4:00 PM' or '16:00'."

    on_date = date.fromisoformat(data["date"])
    doctor = Doctor.query.get(data["doctor_id"]) if data.get("doctor_id") else None

    if not is_slot_available(clinic, on_date, parsed_time, doctor=doctor):
        return "That time just got booked, or isn't available. " + _prompt_for_time(clinic, data)

    data["time"] = parsed_time.strftime("%H:%M")
    save_state(state, "booking_reason", data)
    return "Last thing - what's the reason for your visit? (e.g. Checkup, Cleaning, Toothache)"


def _handle_booking_reason(clinic, phone, state, data, body):
    data["reason"] = body.strip()[:200]

    patient = find_or_create_patient(clinic, phone, name=data.get("name"))
    on_date = date.fromisoformat(data["date"])
    on_time = time.fromisoformat(data["time"])
    doctor = Doctor.query.get(data["doctor_id"]) if data.get("doctor_id") else None

    if not is_slot_available(clinic, on_date, on_time, doctor=doctor):
        save_state(state, "booking_time", data)
        return "Sorry, that slot was just taken. " + _prompt_for_time(clinic, data)

    appointment = book_appointment(clinic, patient, on_date, on_time, doctor=doctor, reason=data["reason"])
    reset_state(state)

    doctor_line = f"\n\nDoctor:\nDr. {doctor.name}" if doctor else ""
    return (
        "Your appointment has been booked successfully.\n\n"
        f"Patient:\n{data.get('name', patient.name)}\n\n"
        f"Date:\n{on_date.strftime('%A, %d %B')}\n\n"
        f"Time:\n{on_time.strftime('%I:%M %p').lstrip('0')}"
        f"{doctor_line}\n\n"
        f"Clinic:\n{clinic.clinic_name}\n\n"
        "We'll confirm shortly. Send 'menu' anytime for more options."
    )


# ---------------------------------------------------------------------------
# View timings flow (read-only, no booking)
# ---------------------------------------------------------------------------

def _handle_timings_date(clinic, phone, state, data, body):
    parsed = parse_natural_date(body, today=clinic.local_today())
    if not parsed:
        return "I couldn't understand that date. Try '15 January' or 'tomorrow'."

    slots = get_available_slots(clinic, parsed, limit=8)
    reset_state(state)

    if not slots:
        return f"No openings on {parsed.strftime('%A, %d %B')}. Send 'menu' to try another date or book anyway."

    lines = [f"- {t.strftime('%I:%M %p').lstrip('0')} (Dr. {d.name})" for d, t in slots]
    return (
        f"Availability for {parsed.strftime('%A, %d %B')}:\n\n" + "\n".join(lines) +
        "\n\nSend 'menu' to book one of these."
    )


_STEP_HANDLERS = {
    "menu": _handle_menu,
    "booking_name": _handle_booking_name,
    "booking_phone": _handle_booking_phone,
    "booking_date": _handle_booking_date,
    "booking_doctor": _handle_booking_doctor,
    "booking_time": _handle_booking_time,
    "booking_reason": _handle_booking_reason,
    "timings_date": _handle_timings_date,
}


# ---------------------------------------------------------------------------
# Small natural-language date/time parsing helpers (no external NLP needed)
# ---------------------------------------------------------------------------

def parse_natural_date(text: str, today: date = None):
    text = text.strip().lower()
    today = today or date.today()

    if text in ("today",):
        return today
    if text in ("tomorrow", "tmrw"):
        return today + timedelta(days=1)

    for i, day_name in enumerate(WEEKDAYS):
        if day_name in text or day_name[:3] in text:
            days_ahead = (i - today.weekday()) % 7
            days_ahead = days_ahead or 7  # always the *next* occurrence
            return today + timedelta(days=days_ahead)

    # ISO format: 2026-01-15
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass

    # Slash format: 15/01/2026 or 15/01
    match = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", text)
    if match:
        day_n, month_n = int(match.group(1)), int(match.group(2))
        year_n = int(match.group(3)) if match.group(3) else today.year
        if year_n < 100:
            year_n += 2000
        try:
            candidate = date(year_n, month_n, day_n)
            if candidate < today and not match.group(3):
                candidate = date(year_n + 1, month_n, day_n)
            return candidate
        except ValueError:
            pass

    # "15 January" / "January 15" style
    for i, month_name in enumerate(MONTHS, start=1):
        if month_name in text or month_name[:3] in text:
            day_match = re.search(r"\b(\d{1,2})\b", text)
            if day_match:
                day_n = int(day_match.group(1))
                year_n = today.year
                try:
                    candidate = date(year_n, i, day_n)
                    if candidate < today:
                        candidate = date(year_n + 1, i, day_n)
                    return candidate
                except ValueError:
                    return None
    return None


def parse_natural_time(text: str):
    text = text.strip().lower()

    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridiem = match.group(3)

    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    if hour > 23 or minute > 59:
        return None

    try:
        return time(hour, minute)
    except ValueError:
        return None
