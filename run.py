"""
One-button runner for generating and sending emails using settings.

Edit values in app_settings.py:
- GENERATE_SETTINGS: controls topic research and list creation
- SEND_SETTINGS: controls which files are sent and logging

Then run: python run.py
"""

from app_settings import GENERATE_SETTINGS, SEND_SETTINGS
from generate_emails import generate_with_settings
from send_email import send_with_settings


def main():
    generate_with_settings(GENERATE_SETTINGS)
    send_with_settings(SEND_SETTINGS)


if __name__ == "__main__":
    main()

