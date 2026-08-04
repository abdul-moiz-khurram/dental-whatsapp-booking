from flask import Blueprint, request, current_app

from app.models import Clinic
from app.chatbot.providers import get_provider
from app.chatbot.providers.meta_provider import MetaProvider
from app.chatbot.engine import handle_incoming_message

chatbot_bp = Blueprint("chatbot", __name__)


def _resolve_clinic(request) -> Clinic:
    """
    Multi-tenant lookup: the number the patient messaged (the clinic's
    WhatsApp Business number) tells us which clinic this conversation
    belongs to. Twilio sends this as `To`; Meta sends it inside the payload
    metadata. For a single-clinic install this always resolves to the one
    clinic row.
    """
    to_number = request.form.get("To", "").replace("whatsapp:", "")
    if not to_number:
        payload = request.get_json(silent=True) or {}
        try:
            to_number = payload["entry"][0]["changes"][0]["value"]["metadata"]["display_phone_number"]
        except (KeyError, IndexError):
            to_number = None

    if to_number:
        clinic = Clinic.query.filter_by(whatsapp_number=to_number).first()
        if clinic:
            return clinic

    # Fall back to the only clinic on single-tenant installs.
    return Clinic.query.first()


@chatbot_bp.route("/whatsapp", methods=["GET", "POST"])
def whatsapp_webhook():
    clinic = _resolve_clinic(request)
    provider_name = (clinic.whatsapp_provider if clinic and clinic.whatsapp_provider else None) or \
        current_app.config.get("WHATSAPP_PROVIDER", "twilio")

    # Meta requires a one-time GET handshake to verify the webhook URL.
    if request.method == "GET" and provider_name == "meta":
        return MetaProvider.verify_webhook(request, clinic=clinic)

    provider = get_provider(clinic)
    incoming = provider.parse_incoming(request)

    if not incoming.get("from") or incoming.get("body") is None:
        return provider.build_webhook_response()

    if not clinic:
        current_app.logger.error("No clinic configured for incoming WhatsApp message.")
        return provider.build_webhook_response("This clinic hasn't finished setup yet. Please try again shortly.")

    if incoming.get("has_media") and not incoming.get("body"):
        # We don't process images/voice notes/documents yet - acknowledge
        # rather than silently ignoring them, which reads as the clinic
        # not responding at all.
        reply_text = (
            "Thanks for sending that - one of our team will take a look. "
            "In the meantime, reply 'menu' to book an appointment or ask a question."
        )
    else:
        reply_text = handle_incoming_message(clinic, incoming["from"], incoming["body"])

    if reply_text is None:
        # A human has taken over this conversation - the bot stays silent
        # and lets staff reply manually from the dashboard.
        return provider.build_webhook_response()

    if provider_name == "meta":
        # Meta needs the reply sent as a separate API call.
        provider.send_message(incoming["from"], reply_text)
        return provider.build_webhook_response()

    return provider.build_webhook_response(reply_text)
