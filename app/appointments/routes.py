import csv
import io

from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Appointment, Patient, User

appointments_bp = Blueprint("appointments", __name__, template_folder="../templates/dashboard")


def _scoped_query():
    """
    Every appointment list is scoped to the clinic - and, if the logged-in
    user is a dentist with a linked doctor profile, further scoped to just
    their own appointments. Receptionists and owners see everything.
    """
    query = Appointment.query.filter_by(clinic_id=current_user.clinic_id)
    if current_user.role == User.ROLE_DENTIST and current_user.doctor_id:
        query = query.filter_by(doctor_id=current_user.doctor_id)
    return query


@appointments_bp.route("/")
@login_required
def list_appointments():
    status_filter = request.args.get("status", "all")
    search = request.args.get("q", "").strip()

    query = _scoped_query()
    if status_filter != "all":
        query = query.filter_by(status=status_filter)

    if search:
        query = query.join(Patient).filter(
            db.or_(Patient.name.ilike(f"%{search}%"), Patient.phone.ilike(f"%{search}%"))
        )

    appointments = query.order_by(
        Appointment.appointment_date.desc(), Appointment.appointment_time.desc()
    ).all()

    return render_template(
        "dashboard/appointments.html",
        appointments=appointments,
        status_filter=status_filter,
        search=search,
    )


@appointments_bp.route("/export.csv")
@login_required
def export_csv():
    appointments = _scoped_query().order_by(Appointment.appointment_date.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Time", "Patient", "Phone", "Doctor", "Reason", "Status"])
    for a in appointments:
        writer.writerow([
            a.appointment_date.isoformat(),
            a.appointment_time.strftime("%H:%M"),
            a.patient.name or "",
            a.patient.phone,
            f"Dr. {a.doctor.name}" if a.doctor else "No preference",
            a.reason or "",
            a.status,
        ])

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=appointments.csv"},
    )


@appointments_bp.route("/<int:appointment_id>/confirm", methods=["POST"])
@login_required
def confirm(appointment_id):
    appt = _scoped_query().filter_by(id=appointment_id).first_or_404()
    appt.status = Appointment.STATUS_CONFIRMED
    appt.confirmed_by_id = current_user.id
    db.session.commit()
    flash("Appointment confirmed.", "success")
    return redirect(request.referrer or url_for("appointments.list_appointments"))


@appointments_bp.route("/<int:appointment_id>/cancel", methods=["POST"])
@login_required
def cancel(appointment_id):
    appt = _scoped_query().filter_by(id=appointment_id).first_or_404()
    appt.status = Appointment.STATUS_CANCELLED
    appt.cancelled_by_id = current_user.id
    db.session.commit()
    flash("Appointment cancelled.", "success")
    return redirect(request.referrer or url_for("appointments.list_appointments"))


@appointments_bp.route("/<int:appointment_id>/complete", methods=["POST"])
@login_required
def complete(appointment_id):
    appt = _scoped_query().filter_by(id=appointment_id).first_or_404()
    appt.status = Appointment.STATUS_COMPLETED
    db.session.commit()
    return redirect(request.referrer or url_for("appointments.list_appointments"))


@appointments_bp.route("/<int:appointment_id>/no-show", methods=["POST"])
@login_required
def no_show(appointment_id):
    appt = _scoped_query().filter_by(id=appointment_id).first_or_404()
    appt.status = Appointment.STATUS_NO_SHOW
    db.session.commit()
    flash("Marked as a no-show.", "info")
    return redirect(request.referrer or url_for("appointments.list_appointments"))
