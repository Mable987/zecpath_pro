from django.core.management.base import BaseCommand
from core.automation import run_auto_shortlisting_platform_wide
 
 
class Command(BaseCommand):
    help = "Evaluate every 'applied' application against its job's auto-shortlist/reject thresholds."
 
    def handle(self, *args, **options):
        results = run_auto_shortlisting_platform_wide(changed_by=None)
 
        shortlisted = sum(1 for r in results if r["action"] == "auto_shortlisted")
        rejected = sum(1 for r in results if r["action"] == "auto_rejected")
        skipped = sum(1 for r in results if r["action"] in ("skipped", "no_action"))
 
        self.stdout.write(self.style.SUCCESS(
            f"Auto-shortlisting run complete: {len(results)} applications evaluated, "
            f"{shortlisted} shortlisted, {rejected} rejected, {skipped} left for manual review."
        ))