from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.extensions import db, limiter
from app.models import User, Clinic
from app.email_utils import send_email

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")

RESET_TOKEN_MAX_AGE_SECONDS = 60 * 60  # 1 hour


def _get_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.overview"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if user and user.is_active_staff and user.check_password(password):
            login_user(user)
            next_url = request.args.get("next")
            return redirect(next_url or url_for("dashboard.overview"))

        if user and not user.is_active_staff:
            flash("This account has been deactivated. Contact your clinic owner.", "error")
        else:
            flash("Incorrect username or password.", "error")

    return render_template("auth/login.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def signup():
    """
    Self-service signup for a brand-new clinic. This creates the Clinic row
    and its first (owner) user in one step - there's no separate "invite a
    clinic" admin flow, since each install is meant to serve one clinic that
    sets itself up. Additional staff/dentist logins are added afterwards
    from Dashboard > Team (owner-only).
    """
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.overview"))

    if request.method == "POST":
        clinic_name = request.form.get("clinic_name", "").strip()
        owner_name = request.form.get("owner_name", "").strip()
        whatsapp_number = request.form.get("whatsapp_number", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = []
        if not clinic_name:
            errors.append("Clinic name is required.")
        if not owner_name:
            errors.append("Owner name is required.")
        if not whatsapp_number:
            errors.append("The clinic's WhatsApp business number is required.")
        if not username:
            errors.append("Please choose a username.")
        if not email or "@" not in email:
            errors.append("A valid email is required - it's how you'll reset your password if you're ever locked out.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm_password:
            errors.append("Passwords don't match.")
        if username and User.query.filter_by(username=username).first():
            errors.append("That username is already taken.")
        if email and User.query.filter_by(email=email).first():
            errors.append("An account with that email already exists.")
        if whatsapp_number and Clinic.query.filter_by(whatsapp_number=whatsapp_number).first():
            errors.append("A clinic is already registered with that WhatsApp number.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("auth/signup.html", form=request.form)

        clinic = Clinic(
            clinic_name=clinic_name,
            owner_name=owner_name,
            phone=request.form.get("phone", "").strip(),
            whatsapp_number=whatsapp_number,
            address=request.form.get("address", "").strip(),
        )
        db.session.add(clinic)
        db.session.flush()  # get clinic.id before creating the user

        user = User(clinic_id=clinic.id, username=username, email=email, role=User.ROLE_OWNER)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        send_email(
            to=email,
            subject="Welcome to Recall",
            body=(
                f"Hi {owner_name},\n\n"
                f"Your Recall account for {clinic_name} is ready.\n\n"
                "Next steps: add your first doctor, then connect your WhatsApp "
                "number from Clinic Settings so patients can start booking.\n\n"
                "- Recall"
            ),
        )
        flash(f"Welcome, {owner_name.split()[0]}! Your clinic account is ready.", "success")
        return redirect(url_for("dashboard.overview"))

    return render_template("auth/signup.html", form={})


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first() if email else None

        if user:
            token = _get_serializer().dumps({"user_id": user.id})
            reset_url = url_for("auth.reset_password", token=token, _external=True)
            send_email(
                to=user.email,
                subject="Reset your Recall password",
                body=(
                    f"Hi {user.username},\n\n"
                    "Someone requested a password reset for your Recall account. "
                    "If this was you, use the link below - it expires in 1 hour:\n\n"
                    f"{reset_url}\n\n"
                    "If you didn't request this, you can safely ignore this email."
                ),
            )

        # Always show the same message, whether or not the email matched -
        # this avoids leaking which emails have accounts.
        flash("If that email is registered, a reset link has been sent.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        data = _get_serializer().loads(token, max_age=RESET_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired:
        flash("That reset link has expired. Please request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))
    except BadSignature:
        flash("That reset link isn't valid.", "error")
        return redirect(url_for("auth.forgot_password"))

    user = User.query.get(data.get("user_id"))
    if not user:
        flash("That reset link isn't valid.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("auth/reset_password.html", token=token)
        if password != confirm_password:
            flash("Passwords don't match.", "error")
            return render_template("auth/reset_password.html", token=token)

        user.set_password(password)
        db.session.commit()
        flash("Your password has been updated. Please sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
