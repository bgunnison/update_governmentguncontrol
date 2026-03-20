# ggcemailer

`Update Government Gun Control` is a utility that automates researching topics related to gun control. It categorizes the updates and sends summaries and supporting links to the website `governmentguncontrol.com`.

Specifically this generates topic-based email drafts with OpenAI and sends them through Gmail to a wordpress web site using settings stored in this repository.

## What the project does

- `generate_emails.py` creates email-list text files in `emails/`
- `send_email.py` reads those files, validates source links, and sends each entry
- `run.py` runs generation and sending back-to-back using `app_settings.py`

## Requirements

- Python 3.10+
- Packages:

```powershell
python -m pip install requests yagmail duckduckgo-search
```

## Configuration

Edit `app_settings.py` to control generation and sending behavior.

Create a `personal.py` file in the repository root for secrets and personal values. This file is gitignored.

Example:

```python
"""
Configuration for email sending and topic selection.

Prompt guidance:
  "Please research gun control in 2026, categorize the information by the
  headings on https://www.governmentguncontrol.com/, and generate a text file
  for each category. Each file should contain multiple email entries separated
  by ---EMAIL_SEPARATOR---, with actual HTTP links to the sources."
"""

# Your Gmail credentials
SENDER_EMAIL = "your-email@gmail.com"
# generate a password to have an app send gmail
SENDER_PASSWORD = "your-generated-16-char-code"

# Recipient email address
# To generate a secret email address for publishing posts to WordPress, you must enable the Post by Email feature within your site's settings # or through the Jetpack plugin. This feature creates a unique, private address that converts any sent email into a live blog post, with the # email subject becoming the post title.
RECIPIENT_EMAIL = "your-generated@post.wordpress.com"

# OpenAI API key (consider moving to an environment variable for safety)
OPENAI_API_KEY = "your-key-here"

# Reference site whose headings/categories guide research
REFERENCE_SITE = "https://www.governmentguncontrol.com/"

# Topics to research (list of names, not URLs)
WEBSITE_TOPICS = [
    "Amendments",
    "Politics",
    "Law",
    "Legislation",
    "Opinion",
    "Activism",
    "Ethics",
    "Religion",
    "Culture",
]

```

Notes:

- `OPENAI_API_KEY` can also come from the `OPENAI_API_KEY` environment variable.
- `WEBSITE_TOPICS` can be overridden in `GENERATE_SETTINGS["topics"]`.
- Gmail sending expects an app password for the sender account.

## Usage

Run both generation and sending:

```powershell
python run.py
```

Run only generation:

```powershell
python generate_emails.py
```

Run only sending:

```powershell
python send_email.py
```

## Output

- Generated email lists: `emails/*.txt`
- Generation log: `emails/generate_log.jsonl`
- Send log: `emails/send_log.jsonl`
