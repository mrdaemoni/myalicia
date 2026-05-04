"""
core.intents — lightweight intent detection helpers.

These are fast pre-LLM classifiers used in the handle_message pipeline
to decide whether a message needs a special downstream path before any
model call. Cheap to compute and easy to extend.

Right now: a single email-intent detector. As more intent classes
emerge (calendar, task, search-vs-question), they land here.
"""
from __future__ import annotations

EMAIL_PHRASES: tuple[str, ...] = (
    "send an email",
    "send email",
    "email to",
    "write an email",
    "shoot an email",
    "drop an email",
    "send a message to",
)


def detect_email_intent(text: str) -> bool:
    """Return True if the message text appears to request sending an email.

    Conservative phrase-match — favors precision (false negatives are
    fine; false positives trigger the email-confirmation flow which is
    annoying). Case-insensitive.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in EMAIL_PHRASES)


__all__ = [
    "EMAIL_PHRASES",
    "detect_email_intent",
]
