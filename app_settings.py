"""
Application settings for generation and sending.

Edit values below instead of using command-line flags.

Notes
- OPENAI_API_KEY: Read from environment or personal.py by default. You can
  override it here by setting GENERATE_SETTINGS["api_key"] to a string.
- WEBSITE_TOPICS: Comes from personal.py. You may override topics here by
  listing topic names in GENERATE_SETTINGS["topics"].
"""

# Generation settings
GENERATE_SETTINGS = {
    # Topics to generate. Use [] or None to use WEBSITE_TOPICS from personal.py.
    "topics": None,
    # Output directory for generated email lists
    "out": "emails",
    # OpenAI model to use
    "model": "gpt-4o-mini",
    # Target number of items per topic
    "num": 5,
    # Minimum acceptable items to keep (set to 0 to require exactly num)
    "min_ok": 3,
    # Maximum generation attempts per topic
    "attempts": 1,
    # Sampling temperature (lower is more focused)
    "temp": 0.2,
    # Optional: set to a string to override env/personal.py key, or leave None
    "api_key": None,
    # JSONL log path for generation events
    "gen_log": "emails/generate_log.jsonl",
    # Curate real sources first and inject them (prevents hallucinated URLs)
    "curate": True,
    # Max search results considered per topic during curation
    "results": 12,
}

# Sending settings
SEND_SETTINGS = {
    # Specific files to send; leave [] or None to scan the directory below
    "files": None,
    # Directory to scan for email list files
    "dir": "emails",
    # Glob for files in the directory
    "glob": "*.txt",
    # Process at most this many files (0 means no limit). Newest last.
    "limit": 0,
    # Dry run: parse and log but do not send emails
    "dry_run": False,
    # JSONL log path for sent entries
    "log": "emails/send_log.jsonl",
    # Resend even if an entry is already logged as sent
    "resend": False,
}

