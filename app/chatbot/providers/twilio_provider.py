from flask import current_app, Response

from .base import WhatsAppProvider


class TwilioProvider(WhatsAppProvider):
    """
    Integrates with Twilio's WhatsApp API.
    https://www.twilio.com/docs/whatsapp

    Twilio posts incoming messages as application/x-www-form-urlencoded
    webhooks, and is happy to receive the reply as TwiML/XML in the
    webhook's HTTP response - so no outbound API call is required for the
    simple reply-to-a-message case.
    """

    def __init__(self, clinic=None):
        # A clinic's own credentials (entered in Clinic Settings) always take
        # priority; server-wide Config values are only a fallback so single
        # clinic installs configured the old way (via .env) keep working.
        self.clinic = clinic

    def _credentials(self):
        if self.clinic and self.clinic.twilio_account_sid:
            return (
                self.clinic.twilio_account_sid,
                self.clinic.get_twilio_auth_token(),
                self.clinic.twilio_whatsapp_from,
            )
        return (
            current_app.config.get("TWILIO_ACCOUNT_SID"),
            current_app.config.get("TWILIO_AUTH_TOKEN"),
            current_app.config.get("TWILIO_WHATSAPP_FROM"),
        )

    def parse_incoming(self, request):
        form = request.form
        return {
            "from": (form.get("From") or "").replace("whatsapp:", ""),
            "body": (form.get("Body") or "").strip(),
            "message_id": form.get("MessageSid"),
            "has_media": int(form.get("NumMedia", 0) or 0) > 0,
        }

    def send_message(self, to: str, body: str):
        """
        Used for proactive messages (e.g. reminders) outside the immediate
        webhook reply. Requires the Twilio SDK / REST call.
        """
        import requests

        sid, token, from_number = self._credentials()

        if not (sid and token and from_number):
            current_app.logger.warning("Twilio credentials are not configured; message not sent.")
            return

        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        requests.post(
            url,
            auth=(sid, token),
            data={
                "From": from_number,
                "To": f"whatsapp:{to}",
                "Body": body,
            },
            timeout=10,
        )

    def build_webhook_response(self, reply_text: str = None):
        if not reply_text:
            return Response(status=204)

        escaped = (
            reply_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escaped}</Message></Response>'
        return Response(twiml, mimetype="application/xml")
