from django.core.management.base import BaseCommand
from django.db import transaction

from core.demo import run_demo
from core.setup import ensure_masters, ensure_users


class Command(BaseCommand):
    help = "Create roles, users, chart of accounts and master data; optionally load the demo scenario."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Load the end-to-end demo scenario")
        parser.add_argument("--password", default="Fitout@123", help="Password for the created users")

    def handle(self, *args, **opts):
        with transaction.atomic():
            groups = ensure_masters(self.stdout)
            ensure_users(groups, opts["password"], self.stdout)
            if opts["demo"]:
                from sales.models import Lead

                if Lead.objects.exists():
                    self.stdout.write("Demo data already loaded; skipping.")
                else:
                    run_demo(self.stdout)
        self.stdout.write(self.style.SUCCESS("Fit-Out ERP is ready."))
