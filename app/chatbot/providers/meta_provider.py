from flask import current_app, Response, jsonify

from .base import WhatsAppProvider


class MetaProvider(WhatsAppProvider):
    """
    Integrates with Meta's official WhatsApp Business Cloud API.
    https://developers.facebook.com/docs/whatsapp/cloud-api

    Unlike Twilio, Meta's webhook expects a bare 200 OK - any reply must be
    sent as a separate authenticated API call, and there's a one-time GET
    verification handshake using META_VERIFY_TOKEN.
    """

    def __init__(self, clinic=None):
        self.clinic = clinic

    def _credentials(self):
        if self.clinic and self.clinic.meta_phone_number_id:
            return self.clinic.meta_phone_number_id, self.clinic.get_meta_access_token()
        return (
            current_app.config.get("META_PHONE_NUMBER_ID"),
            current_app.config.get("META_ACCESS_TOKEN"),
        )

    def parse_incoming(self, request):
        payload = request.get_json(silent=True) or {}
        try:
            entry = payload["entry"][0]["changes"][0]["value"]
            message = entry["messages"][0]
            return {
                "from": "+" + message["from"],
                "body": message.get("text", {}).get("body", "").strip(),
                "message_id": message.get("id"),
                "has_media": message.get("type") not in (None, "text"),
            }
        except (KeyError, IndexError):
            return {"from": None, "body": None, "message_id": None, "has_media": False}

    def send_message(self, to: str, body: str):
        import requests

        phone_number_id, access_token = self._credentials()

        if not (phone_number_id and access_token):
            current_app.logger.warning("Meta credentials are not configured; message not sent.")
            return

        url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
        requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to.lstrip("+"),
                "type": "text",
                "text": {"body": body},
            },
            timeout=10,
        )

    def build_webhook_response(self, reply_text: str = None):
        # Meta doesn't accept the reply inline; it was already sent via
        # send_message(). The webhook itself just needs to acknowledge receipt.
        return jsonify(status="received"), 200

    @staticmethod
    def verify_webhook(request, clinic=None):
        """
        Handles Meta's required GET verification handshake when a webhook
        URL is first registered in the Meta App dashboard. Checks the
        clinic's own verify token first (if one is configured), then falls
        back to the server-wide default.
        """
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        expected = (clinic and clinic.meta_verify_token) or current_app.config.get("META_VERIFY_TOKEN")
        if mode == "subscribe" and token == expected:
            return Response(challenge, status=200)
        return Response("Verification failed", status=403)
