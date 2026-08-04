from abc import ABC, abstractmethod


class WhatsAppProvider(ABC):
    """
    Common interface every WhatsApp integration must implement. Swapping the
    provider in config (WHATSAPP_PROVIDER=twilio|meta) is the only change
    needed anywhere else in the codebase - the chatbot engine only ever
    talks to this interface.
    """

    @abstractmethod
    def parse_incoming(self, request):
        """
        Given a raw Flask request from the provider's webhook, return a
        normalized dict: {"from": "+9231...", "body": "Hi", "message_id": "..."}
        """
        raise NotImplementedError

    @abstractmethod
    def send_message(self, to: str, body: str):
        """Send a plain-text WhatsApp message to `to`."""
        raise NotImplementedError

    @abstractmethod
    def build_webhook_response(self, reply_text: str = None):
        """
        Some providers (Twilio) expect a TwiML/XML response body from the
        webhook itself; others (Meta) just want a 200 OK and send replies
        via a separate API call. This lets each provider decide.
        """
        raise NotImplementedError
