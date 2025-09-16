from huey import crontab
from huey.contrib.djhuey import periodic_task
from django_mailbox.models import Mailbox

@periodic_task(crontab(minute='*/2'))
def fetch_mail():
    for mbox in Mailbox.objects.filter(active=True):
        mbox.process_new_mail()
