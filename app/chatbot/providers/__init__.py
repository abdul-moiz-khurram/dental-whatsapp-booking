from flask import current_app

from .base import WhatsAppProvider
from .twilio_provider import TwilioProvider
from .meta_provider import MetaProvider


def get_provider(clinic=None) -> WhatsAppProvider:
    """
    Returns the configured WhatsApp provider so the rest of the app never
    has to know whether messages travel through Twilio, Meta's Cloud API,
    or something else added later. A clinic's own provider choice (set from
    Clinic Settings > WhatsApp integration) always wins; the server-wide
    Config default is only used as a fallback for installs that haven't
    configured per-clinic credentials yet.
    """
    provider_name = (clinic.whatsapp_provider if clinic and clinic.whatsapp_provider else None) or \
        current_app.config.get("WHATSAPP_PROVIDER", "twilio")
    if provider_name == "meta":
        return MetaProvider(clinic=clinic)
    return TwilioProvider(clinic=clinic)
