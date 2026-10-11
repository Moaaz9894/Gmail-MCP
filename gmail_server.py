"""MCP server exposing Gmail as tools (stdio transport).
NOTE: never print() to stdout here - stdout carries the MCP protocol."""
import base64
import re
from email.message import EmailMessage
from typing import Optional

from mcp.server.fastmcp import FastMCP
from gmail_auth import get_service

mcp = FastMCP("gmail")


def _hdr(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _summary(svc, mid):
    m = svc.users().messages().get(
        userId="me", id=mid, format="metadata",
        metadataHeaders=["From", "To", "Subject", "Date"]).execute()
    h = m["payload"]["headers"]
    return {
        "id": m["id"], "thread_id": m["threadId"],
        "from": _hdr(h, "From"), "to": _hdr(h, "To"),
        "subject": _hdr(h, "Subject"), "date": _hdr(h, "Date"),
        "snippet": m.get("snippet", ""),
        "unread": "UNREAD" in m.get("labelIds", []),
    }


def _search(query: str, max_results: int):
    svc = get_service()
    res = svc.users().messages().list(
        userId="me", q=query, maxResults=max(1, min(max_results, 25))).execute()
    emails = [_summary(svc, m["id"]) for m in res.get("messages", [])]
    return {"query_used": query, "count": len(emails), "emails": emails}


def _find_part(payload, mime):
    if payload.get("mimeType", "") == mime and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        found = _find_part(part, mime)
        if found:
            return found
    return ""


def _send_raw(svc, msg: EmailMessage, thread_id: Optional[str] = None):
    body = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread_id:
        body["threadId"] = thread_id
    return svc.users().messages().send(userId="me", body=body).execute()


@mcp.tool()
def search_emails(query: str, max_results: int = 10) -> dict:
    """Search the mailbox using Gmail search syntax (e.g. 'from:bob subject:invoice newer_than:7d').
    Returns id, sender, subject, date, snippet for each match."""
    return _search(query, max_results)


@mcp.tool()
def filter_emails(sender: Optional[str] = None, subject_contains: Optional[str] = None,
                  label: Optional[str] = None, unread_only: bool = False,
                  has_attachment: bool = False, after: Optional[str] = None,
                  before: Optional[str] = None, max_results: int = 10) -> dict:
    """Filter emails by structured criteria. Dates use YYYY/MM/DD. At least one criterion is required."""
    parts = []
    if sender: parts.append(f"from:{sender}")
    if subject_contains: parts.append(f'subject:("{subject_contains}")')
    if label: parts.append(f"label:{label}")
    if unread_only: parts.append("is:unread")
    if has_attachment: parts.append("has:attachment")
    if after: parts.append(f"after:{after}")
    if before: parts.append(f"before:{before}")
    if not parts:
        return {"error": "Provide at least one filter criterion."}
    return _search(" ".join(parts), max_results)


@mcp.tool()
def read_email(message_id: str) -> dict:
    """Read the full content (headers + plain-text body) of one email by its id."""
    svc = get_service()
    m = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    h = m["payload"]["headers"]
    text = _find_part(m["payload"], "text/plain")
    if not text:
        html = _find_part(m["payload"], "text/html")
        text = re.sub(r"<[^>]+>", " ", html)
    return {"id": m["id"], "thread_id": m["threadId"], "from": _hdr(h, "From"),
            "to": _hdr(h, "To"), "subject": _hdr(h, "Subject"), "date": _hdr(h, "Date"),
            "body": re.sub(r"\n{3,}", "\n\n", text).strip()[:6000]}


@mcp.tool()
def send_email(to: str, subject: str, body: str, cc: Optional[str] = None) -> dict:
    """Send a new plain-text email from the user's Gmail account."""
    svc = get_service()
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    if cc:
        msg["Cc"] = cc
    msg.set_content(body)
    sent = _send_raw(svc, msg)
    return {"status": "sent", "id": sent["id"], "to": to, "subject": subject}


@mcp.tool()
def reply_to_email(message_id: str, body: str) -> dict:
    """Reply (in the same thread) to the email with the given id."""
    svc = get_service()
    orig = svc.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"]).execute()
    h = orig["payload"]["headers"]
    to = _hdr(h, "Reply-To") or _hdr(h, "From")
    subject = _hdr(h, "Subject")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    mid = _hdr(h, "Message-ID")
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    if mid:
        msg["In-Reply-To"] = mid
        msg["References"] = (_hdr(h, "References") + " " + mid).strip()
    msg.set_content(body)
    sent = _send_raw(svc, msg, thread_id=orig["threadId"])
    return {"status": "replied", "id": sent["id"], "to": to, "subject": subject}


@mcp.tool()
def create_auto_filter(from_address: str, label_name: str,
                       skip_inbox: bool = False, mark_read: bool = False) -> dict:
    """Create a persistent Gmail filter: future mail from `from_address` gets `label_name`
    (label is created if missing); optionally skips the inbox and/or is marked read."""
    svc = get_service()
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    lid = next((l["id"] for l in labels if l["name"].lower() == label_name.lower()), None)
    if not lid:
        lid = svc.users().labels().create(userId="me", body={"name": label_name}).execute()["id"]
    action = {"addLabelIds": [lid]}
    remove = (["INBOX"] if skip_inbox else []) + (["UNREAD"] if mark_read else [])
    if remove:
        action["removeLabelIds"] = remove
    svc.users().settings().filters().create(
        userId="me", body={"criteria": {"from": from_address}, "action": action}).execute()
    return {"status": "filter_created", "from": from_address, "label": label_name}


if __name__ == "__main__":
    mcp.run(transport="stdio")
