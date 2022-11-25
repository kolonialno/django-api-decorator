import json
import logging
from importlib import import_module
from pathlib import Path

from django.apps import AppConfig
from django.conf import settings

from .openapi import generate_api_spec

logger = logging.getLogger(__name__)


class ApiToolsConfig(AppConfig):
    name = "tienda.api_tools"

    def ready(self) -> None:

        if not getattr(settings, "OPENAPI_AUTO_GENERATE", False):
            return

        urlpatterns = import_module("tienda.urls.base").urlpatterns

        api_spec = generate_api_spec(urlpatterns=urlpatterns)

        base_path = (
            Path(__file__).parent / Path("../../frontend/api-generated/")
        ).resolve()

        # Ensure that base path exists
        base_path.mkdir(parents=True, exist_ok=True)

        path = base_path / "schemas.json"
        with open(path, "w") as f:
            json.dump(api_spec, f, indent=4)
            logger.info("Wrote OpenAPI schema to %s", path)
