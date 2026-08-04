"""
One-time setup script for a new clinic install.

Usage:
    python seed.py
"""
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Clinic, User, Doctor

app = create_app()

with app.app_context():
    db.create_all()

    if Clinic.query.first():
        print("A clinic already exists - skipping seed. Delete the database to start over.")
    else:
        clinic = Clinic(
            clinic_name="Smile Dental Clinic",
            owner_name="Dr. Ahmed Khan",
            phone="+92 300 1234567",
            whatsapp_number="+14155238886",  # replace with the clinic's real WhatsApp number
            address="Shahrah-e-Faisal, Karachi",
        )
        db.session.add(clinic)
        db.session.commit()

        doctor = Doctor(
            clinic_id=clinic.id,
            name="Ahmed Khan",
            specialization="General Dentist",
            available_days="mon,tue,wed,thu,fri",
            available_times="09:00-17:00",
        )
        db.session.add(doctor)

        owner = User(clinic_id=clinic.id, username="admin", email="admin@smiledental.example", role=User.ROLE_OWNER)
        owner.set_password("changeme123")
        db.session.add(owner)

        db.session.commit()

        print("Seeded clinic, doctor, and owner account.")
        print("Login at /auth/login with username 'admin' and password 'changeme123'.")
        print("Change this password immediately after first login.")
