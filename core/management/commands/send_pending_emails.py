from django.core.management.base import BaseCommand
from core.email_service import send_pending_emails
 
 
class Command(BaseCommand):
    help = "Send all pending, or due-for-retry, queued emails."
 
    def handle(self, *args, **options):
        result = send_pending_emails()
        self.stdout.write(self.style.SUCCESS(
            f"Email queue processed: {result['total_attempted']} attempted, "
            f"{result['sent']} sent, {result['failed_or_retrying']} failed/retrying."
        ))