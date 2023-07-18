import json
import logging
from importlib import import_module
from pathlib import Path
from typing import Any

from django.conf import settings

from .openapi import generate_api_spec

logger = logging.getLogger(__name__)


def get_api_spec() -> dict[str, Any]:
    if not hasattr(settings, "ROOT_URLCONF"):
        raise ValueError(
            "ROOT_URLCONF must be set in settings in order to generate an api spec."
        )

    urlpatterns = import_module(settings.ROOT_URLCONF).urlpatterns

    return generate_api_spec(urlpatterns=urlpatterns)


def get_path() -> Path:
    if not hasattr(settings, "API_DECORATOR_SCHEMA_PATH"):
        raise ValueError(
            "ROOT_URLCONF must be set in settings in order to save the api spec "
            "to a file."
        )

    path = Path(settings.API_DECORATOR_SCHEMA_PATH)  # type: ignore[misc]

    # Ensure that base path exists
    path.parent.mkdir(parents=True, exist_ok=True)

    return path


def write_schema_file() -> None:
    """
    Generate OpenAPI schema and write it to the file specified in settings.
    """

    api_spec = get_api_spec()
    path = get_path()
    with open(path, "w") as f:
        json.dump(api_spec, f, indent=4)
        logger.info("Wrote OpenAPI schema to %s", path)


def check_schema_file_changes() -> None:
    api_spec = get_api_spec()
    path = get_path()
    with open(path) as f:
        expected = json.dumps(api_spec, indent=4)
        actual = f.read()
        assert actual == expected, "Schema file is not in sync with the current code."
