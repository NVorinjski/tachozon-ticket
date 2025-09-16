# ticket/mail_ingest.py
import os
import imaplib
import email
from email import policy

import msal
from django_mailbox.models import Mailbox


def acquire_access_token():
    tenant_id = os.environ["OAUTH_TENANT_ID"]
    client_id = os.environ["OAUTH_CLIENT_ID"]
    refresh_token = os.environ["OAUTH_REFRESH_TOKEN"]
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scopes = ["https://outlook.office365.com/IMAP.AccessAsUser.All"]

    app = msal.PublicClientApplication(client_id=client_id, authority=authority)
    result = app.acquire_token_by_refresh_token(refresh_token, scopes=scopes)
    if "access_token" not in result:
        raise RuntimeError(f"Token refresh failed: {result.get('error_description') or result}")
    return result["access_token"]


def imap_auth_xoauth2(user, access_token):
    auth_str = f"user={user}\x01auth=Bearer {access_token}\x01\x01"
    imap = imaplib.IMAP4_SSL(os.environ.get("MAIL_HOST", "outlook.office365.com"))
    imap.authenticate("XOAUTH2", lambda _: auth_str.encode("utf-8"))
    return imap


def fetch_and_store(*, mailbox_name="Support", folder=None, mark_seen=True, dry_run=False, limit=None) -> int:
    """
    Holt UNSEEN Mails per IMAP XOAUTH2, speichert sie via django-mailbox (inkl. Attachments & Signals)
    und markiert sie optional als gelesen.

    Returns: Anzahl importierter Nachrichten
    """
    user = os.environ["MAIL_USER"]
    folder = folder or os.environ.get("MAIL_FOLDER", "INBOX")

    access_token = acquire_access_token()
    imap = imap_auth_xoauth2(user, access_token)

    # read-write, damit wir Flags setzen können
    typ, _ = imap.select(folder, readonly=False)
    if typ != "OK":
        imap.logout()
        raise RuntimeError(f"Cannot select folder {folder}")

    # UNSEEN via UID suchen
    typ, data = imap.uid("SEARCH", None, "UNSEEN")
    if typ != "OK":
        imap.close()
        imap.logout()
        return 0

    uids = data[0].split() if data and data[0] else []
    if limit:
        uids = uids[:int(limit)]

    try:
        mailbox = Mailbox.objects.get(name=mailbox_name)
    except Mailbox.DoesNotExist:
        imap.close()
        imap.logout()
        raise RuntimeError(f'Mailbox "{mailbox_name}" not found. Create it in admin.')

    imported = 0
    for uid in uids:
        typ, msg_data = imap.uid("FETCH", uid, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue

        raw_bytes = msg_data[0][1]
        email_msg = email.message_from_bytes(raw_bytes, policy=policy.default)

        if dry_run:
            # nur „anschauen“, nicht speichern und nichts markieren
            continue

        saved = mailbox.process_incoming_message(email_msg)
        if saved:
            imported += 1
            if mark_seen:
                imap.uid("STORE", uid, "+FLAGS", r"(\Seen)")

    imap.close()
    imap.logout()
    return imported

