import logging

from django.core.management import BaseCommand

from django_api_decorator.schema_file import check_schema_file_changes, write_schema_file

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    requires_system_checks = []

    help = "Generates API schemas for views with pydantic types."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            dest="check",
            default=False,
            help="Check that the existing schema matches the code instead of writing.",
        )

    def handle(self, *args, **options):
        check = options.get("check")

        if check:
            check_schema_file_changes()
        else:
            write_schema_file()
