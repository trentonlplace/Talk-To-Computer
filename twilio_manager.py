import json
import os
import smtplib
from email.mime.text import MIMEText

from twilio.rest import Client

import config

_CONTACTS_FILE = os.path.join(os.path.dirname(__file__), "contacts.json")


class TwilioManager:
    def __init__(self):
        self.client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        self.from_number = config.TWILIO_PHONE_NUMBER
        self.messaging_service_sid = config.TWILIO_MESSAGING_SERVICE_SID
        self.my_number = config.MY_PHONE_NUMBER
        self.contacts = self._load_contacts()
        self._gateway_available = bool(config.SMTP_USER and config.SMTP_PASSWORD)

    def _load_contacts(self) -> dict[str, str]:
        try:
            with open(_CONTACTS_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _save_contacts(self):
        with open(_CONTACTS_FILE, "w") as f:
            json.dump(self.contacts, f, indent=2)

    def _resolve_number(self, to: str | None) -> str:
        """Resolve a contact name or phone number. Defaults to T's number."""
        if not to:
            return self.my_number
        # Check contacts (case-insensitive)
        for name, number in self.contacts.items():
            if name.lower() == to.lower():
                return number
        # If it looks like a phone number, use it directly
        if any(c.isdigit() for c in to):
            # Normalize: ensure +1 prefix
            digits = "".join(c for c in to if c.isdigit())
            if len(digits) == 10:
                return f"+1{digits}"
            if len(digits) == 11 and digits.startswith("1"):
                return f"+{digits}"
            return f"+{digits}"
        return ""

    def _number_to_digits(self, number: str) -> str:
        """Strip a phone number to just 10 digits (no country code)."""
        digits = "".join(c for c in number if c.isdigit())
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits

    def _send_via_gateway(self, body: str, to_number: str) -> bool:
        """Send SMS via email-to-SMS gateway. Returns True on success."""
        digits = self._number_to_digits(to_number)
        gateway = config.SMS_DEFAULT_GATEWAY
        recipient = f"{digits}@{gateway}"

        msg = MIMEText(body)
        msg["From"] = config.SMTP_USER
        msg["To"] = recipient
        msg["Subject"] = ""  # No subject for SMS

        try:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.send_message(msg)
            print(f"[sms] Sent via gateway ({gateway}): {recipient}")
            return True
        except Exception as e:
            print(f"[sms] Gateway send failed: {e}")
            return False

    def _send_via_twilio(self, body: str, to_number: str) -> str | None:
        """Send SMS via Twilio. Returns error string on failure, None on success."""
        try:
            if self.messaging_service_sid:
                message = self.client.messages.create(
                    body=body,
                    messaging_service_sid=self.messaging_service_sid,
                    to=to_number,
                )
            else:
                message = self.client.messages.create(
                    body=body,
                    from_=self.from_number,
                    to=to_number,
                )
            print(f"[sms] Sent via Twilio (SID: {message.sid})")
            return None
        except Exception as e:
            print(f"[sms] Twilio send failed: {e}")
            return str(e)

    def send_sms(self, body: str, to: str | None = None) -> str:
        """Send an SMS. Uses email gateway first, falls back to Twilio."""
        to_number = self._resolve_number(to)
        if not to_number:
            return f"ERROR: Unknown contact '{to}'. Use add_contact to add them first."

        display = to or "me"

        # Primary: email-to-SMS gateway
        if self._gateway_available:
            if self._send_via_gateway(body, to_number):
                return f"SMS sent to {display} ({to_number})"
            print("[sms] Gateway failed, falling back to Twilio...")

        # Fallback: Twilio
        err = self._send_via_twilio(body, to_number)
        if err is None:
            return f"SMS sent to {display} ({to_number})"
        return f"SMS failed: {err}"

    def add_contact(self, name: str, phone: str) -> str:
        """Add or update a contact."""
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) == 10:
            phone = f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            phone = f"+{digits}"
        self.contacts[name] = phone
        self._save_contacts()
        print(f"[sms] Contact saved: {name} -> {phone}")
        return f"Contact '{name}' saved with number {phone}"

    def get_contacts(self) -> str:
        """List all contacts."""
        if not self.contacts:
            return "No contacts saved."
        lines = [f"  {name}: {number}" for name, number in self.contacts.items()]
        return "Contacts:\n" + "\n".join(lines)
