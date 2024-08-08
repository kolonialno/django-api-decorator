import json
import logging
from importlib import import_module
from pathlib import Path
from typing import Any

from django.conf import settings
from django.urls.resolvers import URLResolver

from .openapi import generate_api_spec

logger = logging.getLogger(__name__)


def get_api_spec() -> dict[str, Any]:
    if not hasattr(settings, "ROOT_URLCONF"):
        raise ValueError(
            "ROOT_URLCONF must be set in settings in order to generate an api spec."
        )

    urlpatterns = import_module(settings.ROOT_URLCONF).urlpatterns

    ignored_resolvers = getattr(settings, "API_DECORATOR_SCHEMA_IGNORED_RESOLVERS", [])
    resolvers_to_ignore = []

    # iterate through urlpatterns to find resolvers to remove.
    for resolver_or_pattern in urlpatterns:
        if not isinstance(resolver_or_pattern, URLResolver):
            continue

        app_name, namespace = resolver_or_pattern.app_name, resolver_or_pattern.namespace
        if (app_name, namespace) in ignored_resolvers:
            resolvers_to_ignore.append(resolver_or_pattern)

    # Remove ignored resovlers from the urlpatterns sequence.
    for resolver in resolvers_to_ignore:
        urlpatterns.remove(resolver)

    return generate_api_spec(urlpatterns=urlpatterns)


def get_path() -> Path:
    if not hasattr(settings, "API_DECORATOR_SCHEMA_PATH"):
        raise ValueError(
            "API_DECORATOR_SCHEMA_PATH must be set in settings in order to save the api spec "
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
