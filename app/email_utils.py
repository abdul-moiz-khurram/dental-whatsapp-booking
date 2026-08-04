"""
Thin wrapper around Flask-Mail so the rest of the app never has to check
whether SMTP is actually configured. If it isn't (e.g. local development, or
a fresh install before the clinic has set up email), messages are logged
instead of sent, so nothing crashes and developers can still see the content.
"""
from flask import current_app
from flask_mail import Message

from app.extensions import mail


def send_email(to: str, subject: str, body: str):
    if not current_app.config.get("MAIL_SERVER"):
        current_app.logger.info(
            "MAIL_SERVER not configured - email not actually sent.\nTo: %s\nSubject: %s\n\n%s",
            to, subject, body,
        )
        return

    msg = Message(subject=subject, recipients=[to], body=body)
    try:
        mail.send(msg)
    except Exception as exc:  # noqa: BLE001 - log and continue, never crash a request over email
        current_app.logger.error("Failed to send email to %s: %s", to, exc)
