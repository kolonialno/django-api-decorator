import json
import logging
from importlib import import_module
from pathlib import Path

from django.apps import AppConfig
from django.conf import settings

from .openapi import generate_api_spec
from .schema_file import write_schema_file

logger = logging.getLogger(__name__)


class ApiToolsConfig(AppConfig):
    name = "django_api_tools"

    def ready(self) -> None:

        if not getattr(settings, "API_TOOLS_SCHEMA_AUTOGENERATE", False):
            return

        write_schema_file()
