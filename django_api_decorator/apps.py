import logging

from django.apps import AppConfig
from django.conf import settings

from .schema_file import write_schema_file

logger = logging.getLogger(__name__)


class ApiToolsConfig(AppConfig):
    name = "django_api_decorator"

    def ready(self) -> None:
        if not getattr(settings, "API_DECORATOR_SCHEMA_AUTOGENERATE", False):
            return

        write_schema_file()
