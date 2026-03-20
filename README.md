# ggcemailer

`ggcemailer` is a utility that automates researching topics related to gun control. It categorizes the updates and sends them to the website `governmentguncontrol.com`.

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

`duckduckgo-search` is recommended for source curation. The generator has an HTML fallback if it is not installed.

## Configuration

Edit `app_settings.py` to control generation and sending behavior.

Create a `personal.py` file in the repository root for secrets and personal values. This file is gitignored.

Example:

```python
OPENAI_API_KEY = "your-openai-api-key"
WEBSITE_TOPICS = [
    "Background checks",
    "Safe storage",
    "Domestic violence restrictions",
]

SENDER_EMAIL = "your_email@gmail.com"
SENDER_PASSWORD = "your-gmail-app-password"
RECIPIENT_EMAIL = "recipient@example.com"
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
