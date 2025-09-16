# ticket/management/commands/getmail_oauth.py
import os
import sys
import imaplib
import email
from email import policy
from django.core.management.base import BaseCommand, CommandError

import msal
from django_mailbox.models import Mailbox, Message

# ----- OAuth helper -----
def acquire_access_token():
    tenant_id = os.environ["OAUTH_TENANT_ID"]
    client_id = os.environ["OAUTH_CLIENT_ID"]
    refresh_token = os.environ["OAUTH_REFRESH_TOKEN"]
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scopes = ["https://outlook.office365.com/IMAP.AccessAsUser.All"]

    app = msal.PublicClientApplication(client_id=client_id, authority=authority)
    # MSAL empfiehlt: acquire_token_by_refresh_token für Public Clients ok
    result = app.acquire_token_by_refresh_token(refresh_token, scopes=scopes)
    if "access_token" not in result:
        raise RuntimeError(f"Token refresh failed: {result.get('error_description') or result}")
    return result["access_token"]

def imap_auth_xoauth2(user, access_token):
    auth_str = f"user={user}\x01auth=Bearer {access_token}\x01\x01"
    imap = imaplib.IMAP4_SSL(os.environ.get("MAIL_HOST", "outlook.office365.com"))
    imap.authenticate("XOAUTH2", lambda _: auth_str.encode("utf-8"))
    return imap

class Command(BaseCommand):
    help = "Fetches emails from Microsoft 365 via OAuth2 (XOAUTH2) and stores them using django-mailbox."

    def add_arguments(self, parser):
        parser.add_argument("--mailbox", default="Support", help="Name of Mailbox entry to attribute messages to")
        parser.add_argument("--folder", default=None, help="IMAP folder, overrides MAIL_FOLDER")
        parser.add_argument("--dry-run", action="store_true", help="Do not persist messages, just list subjects")

    def handle(self, *args, **opts):
        user = os.environ["MAIL_USER"]
        folder = opts["folder"] or os.environ.get("MAIL_FOLDER", "INBOX")

        # 1) Access-Token holen
        access_token = acquire_access_token()

        # 2) IMAP verbinden + authentifizieren
        imap = imap_auth_xoauth2(user, access_token)

        # 3) Folder wählen
        typ, _ = imap.select(folder, readonly=True)
        if typ != "OK":
            raise CommandError(f"Cannot select folder {folder}")

        # 4) Ungelesene Nachrichten suchen (anpassbar)
        typ, data = imap.search(None, "UNSEEN")
        if typ != "OK":
            self.stdout.write(self.style.WARNING("No UNSEEN messages or search failed"))
            imap.logout()
            return

        ids = data[0].split()
        self.stdout.write(f"Found {len(ids)} unseen message(s)")

        # 5) Nachrichten holen und in django-mailbox speichern
        # Wir hängen die Messages an eine existierende Mailbox in Django
        try:
            mailbox = Mailbox.objects.get(name=opts["mailbox"])
        except Mailbox.DoesNotExist:
            raise CommandError(f'Mailbox "{opts["mailbox"]}" not found. Create one in admin or change --mailbox')

        imported = 0
        for msg_id in ids:
            typ, msg_data = imap.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue

            raw_bytes = msg_data[0][1]
            email_msg = email.message_from_bytes(raw_bytes, policy=policy.default)

            subject = email_msg.get("Subject", "(no subject)")
            self.stdout.write(f" - {subject}")

            if not opts["dry_run"]:
                # django-mailbox: persistieren
                saved = mailbox.process_incoming_message(email_msg)
                imported += 1

        imap.logout()
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} message(s)"))
