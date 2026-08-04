"""
Core scheduling logic.

This is intentionally simple: one clinic, a handful of doctors, fixed slot
durations. No overbooking rules, no multi-chair logic, no insurance/billing
concerns - the brief asks for a booking bot, not a practice management suite.
"""
from datetime import datetime, timedelta, date, time

from app.extensions import db
from app.models import Appointment, Doctor, Patient

DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _slots_for_doctor(doctor: Doctor, on_date: date, slot_minutes: int):
    day_code = DAY_CODES[on_date.weekday()]
    if day_code not in doctor.working_day_codes():
        return []

    start_t, end_t = doctor.working_hours()
    slots = []
    cur = datetime.combine(on_date, start_t)
    end = datetime.combine(on_date, end_t)
    step = timedelta(minutes=slot_minutes)
    while cur + step <= end:
        slots.append(cur.time())
        cur += step
    return slots


def get_available_slots(clinic, on_date: date, doctor: Doctor = None, limit: int = 6):
    """
    Returns a list of (doctor, time) tuples that are free on the given date.
    If a doctor is specified, only that doctor's slots are considered.
    """
    slot_minutes = clinic.slot_duration_minutes or 30
    candidate_doctors = [doctor] if doctor else Doctor.query.filter_by(
        clinic_id=clinic.id, active=True
    ).all()

    booked = {
        (a.doctor_id, a.appointment_time)
        for a in Appointment.query.filter_by(clinic_id=clinic.id, appointment_date=on_date)
        .filter(Appointment.status != Appointment.STATUS_CANCELLED)
        .all()
    }

    available = []
    for doc in candidate_doctors:
        for slot in _slots_for_doctor(doc, on_date, slot_minutes):
            if (doc.id, slot) not in booked:
                available.append((doc, slot))
            if len(available) >= limit:
                return available
    return available


def is_slot_available(clinic, on_date: date, on_time: time, doctor: Doctor = None) -> bool:
    slots = get_available_slots(clinic, on_date, doctor=doctor, limit=10_000)
    if doctor:
        return any(t == on_time for _, t in slots)
    return any(t == on_time for _, t in slots)


def find_or_create_patient(clinic, phone: str, name: str = None) -> Patient:
    patient = Patient.query.filter_by(clinic_id=clinic.id, phone=phone).first()
    if patient:
        if name and not patient.name:
            patient.name = name
            db.session.commit()
        return patient

    patient = Patient(clinic_id=clinic.id, phone=phone, name=name)
    db.session.add(patient)
    db.session.commit()
    return patient


def book_appointment(clinic, patient: Patient, on_date: date, on_time: time, doctor: Doctor = None, reason: str = None) -> Appointment:
    appointment = Appointment(
        clinic_id=clinic.id,
        patient_id=patient.id,
        doctor_id=doctor.id if doctor else None,
        appointment_date=on_date,
        appointment_time=on_time,
        reason=reason,
        status=Appointment.STATUS_PENDING,
    )
    db.session.add(appointment)
    db.session.commit()
    return appointment
