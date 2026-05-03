#!/usr/bin/env python3
"""
Alicia — Skill 03: Gmail Integration
Handles reading, summarising, and sending emails
"""

import os
import base64
import json
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from myalicia.config import config

TOKEN_FILE = os.path.expanduser("~/alicia/config/token.json")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

ALICIA_EMAIL = ""  # TODO: set ALICIA_EMAIL env

# ── Auth ──────────────────────────────────────────────────────────────────────

def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


# ── Reading ───────────────────────────────────────────────────────────────────

def get_message_body(msg: dict) -> str:
    """Extract plain text body from a Gmail message."""
    payload = msg.get("payload", {})
    parts = payload.get("parts", [])

    if not parts:
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        return ""

    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return ""


def get_header(headers: list, name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def fetch_recent_emails(days: int = 1, max_results: int = 20, query: str = "") -> list:
    """Fetch emails from the last N days, optionally filtered by query."""
    service = get_gmail_service()
    after = int((datetime.now() - timedelta(days=days)).timestamp())
    q = f"after:{after}"
    if query:
        q += f" {query}"

    results = service.users().messages().list(
        userId="me", q=q, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="full"
        ).execute()
        headers = msg.get("payload", {}).get("headers", [])
        emails.append({
            "id":      m["id"],
            "subject": get_header(headers, "subject"),
            "from":    get_header(headers, "from"),
            "date":    get_header(headers, "date"),
            "snippet": msg.get("snippet", ""),
            "body":    get_message_body(msg)[:500],  # First 500 chars
        })

    return emails


def get_inbox_summary(days: int = 1) -> str:
    """Generate a plain-language inbox summary for Telegram."""
    emails = fetch_recent_emails(days=days, max_results=30)

    if not emails:
        return f"📭 No new emails in the last {days} day(s)."

    lines = [f"📬 *Inbox summary — last {days} day(s)*\n"]
    for i, e in enumerate(emails[:10], 1):
        sender = e["from"].split("<")[0].strip()
        lines.append(f"{i}. *{e['subject'][:50]}*\n   From: {sender}\n   _{e['snippet'][:80]}_\n")

    if len(emails) > 10:
        lines.append(f"_...and {len(emails) - 10} more._")

    return "\n".join(lines)


def get_financial_emails(days: int = 7) -> list:
    """Fetch emails likely related to finance."""
    financial_terms = "receipt OR invoice OR payment OR transaction OR bank OR statement OR order"
    return fetch_recent_emails(days=days, max_results=50, query=financial_terms)


def summarise_financial_emails(days: int = 7) -> str:
    """Summarise financial emails for Skill 3 spending overview."""
    emails = get_financial_emails(days=days)

    if not emails:
        return f"💳 No financial emails found in the last {days} days."

    lines = [f"💰 *Financial emails — last {days} days* ({len(emails)} found)\n"]
    for e in emails[:15]:
        sender = e["from"].split("<")[0].strip()
        lines.append(f"• *{e['subject'][:50]}*\n  {sender} — _{e['snippet'][:80]}_\n")

    return "\n".join(lines)


# ── Sending ───────────────────────────────────────────────────────────────────

def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email from Alicia's account. Returns True on success."""
    service = get_gmail_service()

    message = MIMEMultipart()
    message["to"]      = to
    message["from"]    = ALICIA_EMAIL
    message["subject"] = subject
    message.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return True


def draft_email(to: str, subject: str, body: str) -> dict:
    """Create a draft without sending. Returns draft info."""
    service = get_gmail_service()

    message = MIMEMultipart()
    message["to"]      = to
    message["from"]    = ALICIA_EMAIL
    message["subject"] = subject
    message.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing Gmail connection...")
    summary = get_inbox_summary(days=1)
    print(summary)