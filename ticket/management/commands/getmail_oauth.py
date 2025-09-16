# ticket/management/commands/getmail_oauth.py
from django.core.management.base import BaseCommand
from ticket.mail_ingest import fetch_and_store


class Command(BaseCommand):
    help = "Fetches emails from Microsoft 365 via OAuth2 (XOAUTH2) and stores them using django-mailbox."

    def add_arguments(self, parser):
        parser.add_argument("--mailbox", default="Support", help="Mailbox.name in Django")
        parser.add_argument("--folder", default=None, help="IMAP folder (default: env MAIL_FOLDER or INBOX)")
        parser.add_argument("--dry-run", action="store_true", help="List only, do not save/mark")
        parser.add_argument("--no-mark-seen", action="store_true",
                            help="Do NOT mark imported messages as \\Seen")
        parser.add_argument("--limit", type=int, default=None, help="Max number of messages to process")

    def handle(self, *args, **opts):
        imported = fetch_and_store(
            mailbox_name=opts["mailbox"],
            folder=opts["folder"],
            mark_seen=not opts["no_mark_seen"],
            dry_run=opts["dry_run"],
            limit=opts["limit"],
        )
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} message(s)"))
