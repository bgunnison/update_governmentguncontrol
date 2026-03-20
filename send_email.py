import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yagmail

# Import credentials from personal.py
# This line assumes you have a file named personal.py in the same directory
# with the following variables defined:
# SENDER_EMAIL = "your_email@gmail.com"
# SENDER_PASSWORD = "your-16-digit-app-password"
from personal import SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL

def remove_broken_links(text):
    """
    Finds all URLs in text, checks each, removes and logs any that are broken.
    Returns the cleaned text.
    """
    url_pattern = r'https?://\S+'
    urls = re.findall(url_pattern, text)
    for url in urls:
        try:
            response = requests.head(url, allow_redirects=True, timeout=5)
            if response.status_code == 404:
                print(f"Removed broken link: {url}")
                text = text.replace(url, '[broken link removed]')
        except requests.RequestException as e:
            print(f"Error checking URL '{url}': {e}")
            text = text.replace(url, '[broken link removed]')
    return text


def prune_broken_source_lines(text: str) -> str:
    """Remove any 'Source:' lines that no longer contain a valid URL.

    This primarily drops lines like 'Source: [broken link removed]' that can
    result from verification replacing bad URLs. It also removes bullet/numbered
    variants (e.g., '- Source:' or '1) Source:').
    """
    lines = text.splitlines()
    out = []
    source_prefix = re.compile(r"(?i)^\s*(?:[-*•–—]|\d+[\).])?\s*source\s*:\s*")
    for ln in lines:
        if source_prefix.match(ln):
            # Drop if placeholder present or no remaining http(s) URL
            if "[broken link removed]" in ln or not re.search(r"https?://\S+", ln):
                continue
        out.append(ln)
    return "\n".join(out)


def _sanitize_url(u: str) -> str:
    if not u:
        return u
    while u and u[-1] in ")]}.,;:'\">":
        u = u[:-1]
    return u


def _extract_urls(text: str):
    # Stop at whitespace or common closing punctuation/brackets
    raw = re.findall(r"https?://[^\s\]\)\}>\'\"<>]+", text)
    seen = set()
    urls = []
    for r in raw:
        u = _sanitize_url(r)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def normalize_source_lines(text: str) -> str:
    """
    Deduplicate and standardize 'Source:' lines.
    - Removes lines that look like sources (including bullets like "- Source:" or "– Source:")
    - Extracts URLs from those lines
    - Appends unique standardized lines: "Source: <url>"
    """
    lines = text.splitlines()
    body_lines = []
    urls = []
    seen = set()
    source_line_pattern = re.compile(
        r"(?i)^\s*(?:[-*•–—]|\d+[\).])?\s*sources?\s*[:\-]"
    )

    for ln in lines:
        if source_line_pattern.search(ln):
            for u in _extract_urls(ln):
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
            continue
        body_lines.append(ln)

    # Append standardized, unique source lines
    for u in urls:
        body_lines.append(f"Source: {u}")

    return "\n".join([ln for ln in body_lines if ln is not None])


EMAIL_SEPARATOR = "---EMAIL_SEPARATOR---"
SENT_MARK_PREFIX = "X-Sent: "  # ISO-8601 UTC timestamp appended when an entry is sent

def _make_entry_key(file_path: str, index: int, subject: str) -> str:
    return f"{Path(file_path).resolve()}|{index}|{subject.strip()}"


def _load_sent_index(log_path: Path) -> set[str]:
    sent = set()
    if not log_path.exists():
        return sent
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                key = rec.get("key")
                status = rec.get("status")
                if key and status == "sent":
                    sent.add(key)
    except Exception:
        pass
    return sent


def _append_log(log_path: Path, record: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _has_sent_marker(entry_text: str) -> bool:
    for ln in entry_text.splitlines():
        if ln.strip().startswith(SENT_MARK_PREFIX):
            return True
    return False


def _mark_entry_sent(entry_text: str, ts_utc_z: str) -> str:
    if _has_sent_marker(entry_text):
        return entry_text
    parts = entry_text.rstrip("\n").splitlines()
    parts.append(f"{SENT_MARK_PREFIX}{ts_utc_z}")
    return "\n".join(parts)


def _write_entries_back(file_path: str, entries: list[str]) -> None:
    final_text = f"\n{EMAIL_SEPARATOR}\n".join(e.strip() for e in entries if e is not None)
    if not final_text.endswith("\n"):
        final_text += "\n"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(final_text)


def send_emails_from_file(file_path, dry_run=False, log_path: Path | None = None, resend: bool = False):
    """
    Reads the content of a text file, splits it into multiple emails,
    and sends each email.

    Each email within the file should be separated by EMAIL_SEPARATOR.
    The first line of each email content is the subject (with surrounding '**' removed).
    The second line is the category, which becomes the first line of the email body.
    """
    yag_connection = None  # Initialize connection to None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            full_content = f.read()

        # Split the content into individual email bodies
        email_bodies = [e.strip() for e in full_content.split(EMAIL_SEPARATOR) if e.strip()]

        if not email_bodies:
            print(f"No emails found in '{file_path}'. Please ensure they are separated by '{EMAIL_SEPARATOR}'.")
            return

        # Initialize the connection to the SMTP server once
        yag_connection = yagmail.SMTP(SENDER_EMAIL, SENDER_PASSWORD)

        sent_index = set()
        if log_path is not None:
            sent_index = _load_sent_index(log_path)

        sent_count = 0
        skipped_count = 0
        fail_count = 0

        for i, email_body in enumerate(email_bodies):
            lines = email_body.split('\n')
            # Extract subject from the first line, stripping the asterisks
            subject = lines[0].strip().strip('*') if lines else "Update"
            # The rest of the content is the body, starting with the category
            #body = '\n'.join(lines[1:])
            raw_body = '\n'.join(lines[1:])

            # Skip if entry is already marked as sent in the file
            if not resend and _has_sent_marker(email_body):
                print(f"Skipping already-marked-sent email {i+1}/{len(email_bodies)} from '{file_path}' with subject: '{subject}'")
                skipped_count += 1
                continue
            # First normalize and dedupe source lines, then check links
            normalized = normalize_source_lines(raw_body)
            body = remove_broken_links(normalized)
            body = prune_broken_source_lines(body)

            key = _make_entry_key(file_path, i, subject)
            if not resend and key in sent_index:
                print(f"Skipping already-sent email {i+1}/{len(email_bodies)} from '{file_path}' with subject: '{subject}'")
                skipped_count += 1
                continue

            print(f"Prepared email {i+1}/{len(email_bodies)} from '{file_path}' with subject: '{subject}', to {RECIPIENT_EMAIL}")
            if dry_run:
                continue

            # Send the email
            try:
                yag_connection.send(
                    to=RECIPIENT_EMAIL,
                    subject=subject,
                    contents=body,
                )
                print(f"Email {i+1} from '{file_path}' sent successfully to {RECIPIENT_EMAIL}")
                sent_count += 1
                if log_path is not None:
                    _append_log(log_path, {
                        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                        "file": str(Path(file_path).resolve()),
                        "index": i,
                        "subject": subject,
                        "recipient": RECIPIENT_EMAIL,
                        "status": "sent",
                        "key": key,
                    })

                # Mark the entry as sent inside the file immediately (unless dry-run)
                ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                email_bodies[i] = _mark_entry_sent(email_body, ts)
                try:
                    _write_entries_back(file_path, email_bodies)
                except Exception as write_err:
                    print(f"Warning: sent entry marked but failed to update file '{file_path}': {write_err}")
            except Exception as e:
                print(f"Failed to send email {i+1} from '{file_path}': {e}")
                fail_count += 1

    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except Exception as e:
        print(f"An error occurred while processing '{file_path}': {e}")
    finally:
        # Ensure the connection is closed gracefully if it was opened
        if yag_connection:
            yag_connection.close()
        print(f"Summary for {file_path}: sent={sent_count}, skipped={skipped_count}, failed={fail_count}")

def send_with_settings(cfg: dict):
    """Send emails based on settings from app_settings.SEND_SETTINGS.

    cfg keys:
    - files: list[str] | None
    - dir: str
    - glob: str
    - limit: int
    - dry_run: bool
    - log: str
    - resend: bool
    """
    files_cfg = cfg.get("files")
    base_dir = Path(cfg.get("dir", "emails"))
    pattern = cfg.get("glob", "*.txt")
    limit = int(cfg.get("limit", 0))
    dry_run = bool(cfg.get("dry_run", False))
    resend = bool(cfg.get("resend", False))
    log_path = Path(cfg.get("log", "emails/send_log.jsonl"))

    if files_cfg:
        files = list(files_cfg)
    else:
        files = sorted((str(p) for p in base_dir.glob(pattern)), key=lambda p: os.path.getmtime(p))

    if limit and len(files) > limit:
        files = files[-limit:]

    if not files:
        print("No email list files found. Set SEND_SETTINGS['files'] or populate the emails/ directory.")
        return

    for file_path in files:
        print(f"\n--- Processing file: {file_path} ---")
        send_emails_from_file(file_path, dry_run=dry_run, log_path=log_path, resend=resend)


if __name__ == "__main__":
    try:
        from app_settings import SEND_SETTINGS
    except Exception:
        print("Warning: app_settings.py missing; using internal send defaults.")
        SEND_SETTINGS = {
            "files": None,
            "dir": "emails",
            "glob": "*.txt",
            "limit": 0,
            "dry_run": False,
            "log": "emails/send_log.jsonl",
            "resend": False,
        }
    send_with_settings(SEND_SETTINGS)
