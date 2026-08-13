from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 10


def generate_referral_code() -> str:
    """Generate a short, unguessable, URL-safe referral code (fits in a Telegram deep-link payload)."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
