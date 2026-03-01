import json
import os

from twilio.rest import Client

import config

_CONTACTS_FILE = os.path.join(os.path.dirname(__file__), "contacts.json")


class TwilioManager:
    def __init__(self):
        self.client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        self.from_number = config.TWILIO_PHONE_NUMBER
        self.my_number = config.MY_PHONE_NUMBER
        self.contacts = self._load_contacts()

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

    def send_sms(self, body: str, to: str | None = None) -> str:
        """Send an SMS. 'to' can be a contact name or phone number."""
        to_number = self._resolve_number(to)
        if not to_number:
            return f"ERROR: Unknown contact '{to}'. Use add_contact to add them first."
        try:
            message = self.client.messages.create(
                body=body,
                from_=self.from_number,
                to=to_number,
            )
            display = to or "me"
            print(f"[twilio] SMS to {display} ({to_number}): {body[:50]}... (SID: {message.sid})")
            return f"SMS sent to {display} ({to_number})"
        except Exception as e:
            print(f"[twilio] SMS error: {e}")
            return f"SMS failed: {e}"

    def add_contact(self, name: str, phone: str) -> str:
        """Add or update a contact."""
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) == 10:
            phone = f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            phone = f"+{digits}"
        self.contacts[name] = phone
        self._save_contacts()
        print(f"[twilio] Contact saved: {name} -> {phone}")
        return f"Contact '{name}' saved with number {phone}"

    def get_contacts(self) -> str:
        """List all contacts."""
        if not self.contacts:
            return "No contacts saved."
        lines = [f"  {name}: {number}" for name, number in self.contacts.items()]
        return "Contacts:\n" + "\n".join(lines)
