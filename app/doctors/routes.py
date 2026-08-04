from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Doctor
from app.auth.decorators import owner_required

doctors_bp = Blueprint("doctors", __name__, template_folder="../templates/dashboard")

DAY_CHOICES = [
    ("mon", "Mon"), ("tue", "Tue"), ("wed", "Wed"), ("thu", "Thu"),
    ("fri", "Fri"), ("sat", "Sat"), ("sun", "Sun"),
]


@doctors_bp.route("/")
@login_required
def list_doctors():
    doctors = Doctor.query.filter_by(clinic_id=current_user.clinic_id).order_by(Doctor.name).all()
    return render_template("dashboard/doctors.html", doctors=doctors, day_choices=DAY_CHOICES)


@doctors_bp.route("/add", methods=["POST"])
@login_required
@owner_required
def add_doctor():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Doctor name is required.", "error")
        return redirect(url_for("doctors.list_doctors"))

    selected_days = request.form.getlist("available_days")
    start_time = request.form.get("start_time", "09:00")
    end_time = request.form.get("end_time", "17:00")

    doctor = Doctor(
        clinic_id=current_user.clinic_id,
        name=name,
        specialization=request.form.get("specialization", "").strip(),
        available_days=",".join(selected_days) if selected_days else "mon,tue,wed,thu,fri",
        available_times=f"{start_time}-{end_time}",
    )
    db.session.add(doctor)
    db.session.commit()
    flash(f"Dr. {doctor.name} has been added.", "success")
    return redirect(url_for("doctors.list_doctors"))


@doctors_bp.route("/<int:doctor_id>/toggle", methods=["POST"])
@login_required
@owner_required
def toggle_doctor(doctor_id):
    doctor = Doctor.query.filter_by(id=doctor_id, clinic_id=current_user.clinic_id).first_or_404()
    doctor.active = not doctor.active
    db.session.commit()
    return redirect(url_for("doctors.list_doctors"))


@doctors_bp.route("/<int:doctor_id>/delete", methods=["POST"])
@login_required
@owner_required
def delete_doctor(doctor_id):
    doctor = Doctor.query.filter_by(id=doctor_id, clinic_id=current_user.clinic_id).first_or_404()
    db.session.delete(doctor)
    db.session.commit()
    flash("Doctor removed.", "success")
    return redirect(url_for("doctors.list_doctors"))
