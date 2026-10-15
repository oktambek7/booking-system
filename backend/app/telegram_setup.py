"""Register the webhook with Telegram (run once per deployment, and again if the URL or secret changes).

    python -m app.telegram_setup https://<your-api-host>/api/telegram/webhook

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET in the environment.
"""
import sys
from . import telegram
from .config import settings

def main(argv: list[str]) -> int:
    if len(argv) != 1 or not argv[0].startswith("https://"):
        print(__doc__)
        return 2
    if not telegram.configured() or len(settings.telegram_webhook_secret) < 16:
        print("Set TELEGRAM_BOT_TOKEN and a TELEGRAM_WEBHOOK_SECRET of at least 16 characters first.")
        return 2
    print(telegram.register_webhook(argv[0]))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
