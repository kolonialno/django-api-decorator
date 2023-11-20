import dataclasses
import logging
import re
import textwrap
from collections.abc import Callable, Sequence
from typing import Any, cast

import pydantic
from django.http import HttpResponse
from django.urls.resolvers import RoutePattern, URLPattern, URLResolver
from pydantic_core import PydanticUndefined

from .types import ApiMeta

logger = logging.getLogger(__name__)

schema_ref = "#/components/schemas/{model}"


def get_resolved_url_patterns(
    base_patterns: Sequence[URLResolver | URLPattern],
) -> list[tuple[URLPattern, str, str]]:
    """
    Given a list of base URL patterns, this function digs down into the URL hierarchy
    and evaluates the full URLs of all django views that have a simple path (e.g. no
    regex). Returns a list of tuples with each RoutePattern and its full URL.
    """

    def combine_path(existing: str, append: str | None) -> str:
        if not append:
            return existing
        elif existing == "":
            return append
        else:
            return existing + ":" + append

    unresolved_patterns: list[tuple[URLResolver | URLPattern, str, str]] = [
        (url_pattern, "/", "") for url_pattern in base_patterns
    ]
    resolved_urls: list[tuple[URLPattern, str, str]] = []

    while len(unresolved_patterns):
        url_pattern, url_prefix, reverse_path = unresolved_patterns.pop()

        if not isinstance(url_pattern.pattern, RoutePattern):
            logger.debug("Skipping URL that is not simple (e.g. regex or locale url)")
            continue

        # RoutePattern.__str__ returns the actual url pattern
        url = url_prefix + str(url_pattern.pattern)

        # If we are dealing with a URL Resolver we should dig further down.
        if isinstance(url_pattern, URLResolver):
            unresolved_patterns += [
                (child_pattern, url, combine_path(reverse_path, url_pattern.namespace))
                for child_pattern in url_pattern.url_patterns
            ]
        else:
            resolved_urls.append(
                (url_pattern, url, combine_path(reverse_path, url_pattern.name))
            )

    return resolved_urls


def django_path_to_openapi_url_and_parameters(
    path: str,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Returns an OpenAPI URL and the URL parameter specs, given a django url.
    """

    # mapping django url types to openapi types
    url_parameter_type_mapping = {
        "int": "integer",
        "str": "string",
        "slug": "string",
    }

    parameters = []

    def replacer(match: re.Match[str]) -> str:
        parameter_type = match.group(1)
        parameter_name = match.group(2)
        parameters.append(
            {
                "name": parameter_name,
                "in": "path",
                "required": True,
                "schema": {"type": url_parameter_type_mapping.get(parameter_type)},
            }
        )
        return "{" + parameter_name + "}"

    # Replaces e.g. "/x/<str:hello>/<int:hi>/" with "/x/{hello}/{hi}/" and also
    # populates the parameters variable.
    path = re.sub(r"<([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)>", replacer, path)

    return path, parameters


def paths_and_types_for_view(
    *,
    view_name: str,
    callback: Callable[..., HttpResponse],
    resolved_url: str,
    reverse_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    api_meta: ApiMeta | None = getattr(callback, "_api_meta", None)

    assert api_meta is not None

    # Types that should be included in the schema object (referenced via
    # schema_type_ref)
    components: dict[str, Any] = {}

    def to_ref_if_object(schema: dict[str, Any]) -> dict[str, Any]:
        if schema.get("type", None) == "object" and "title" in schema:
            name = schema["title"]
            ref = schema_ref.format(model=name)
            components[name] = schema
            return {"$ref": ref}

        return schema

    if api_meta.response_adapter:
        response_schema = api_meta.response_adapter.json_schema(ref_template=schema_ref)
        if defs := response_schema.pop("$defs", None):
            components.update(defs)
        response_schema = to_ref_if_object(response_schema)
        api_response = {"content": {"application/json": {"schema": response_schema}}}
    else:
        api_response = {}

    request_body = {}
    if api_meta.body_adapter:
        body_schema = api_meta.body_adapter.json_schema(ref_template=schema_ref)
        if defs := body_schema.pop("$defs", None):
            components.update(defs)

        body_schema = to_ref_if_object(body_schema)

        request_body = {
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": body_schema}},
            }
        }

    path, parameters = django_path_to_openapi_url_and_parameters(resolved_url)

    for name, field in api_meta.query_params_model.model_fields.items():
        schema = pydantic.TypeAdapter(field.annotation).json_schema(
            ref_template=schema_ref
        )
        schema = to_ref_if_object(schema)
        if field.default != PydanticUndefined:
            schema["default"] = field.default

        param = {
            "name": field.alias or name,
            "in": "query",
            "required": field.is_required(),
            "schema": schema,
        }
        parameters.append(param)

    # Assuming standard django folder structure with [project name]/[app name]/....
    app_name = callback.__module__.split(".")[1]

    paths = {
        path: {
            api_meta.method.lower(): {
                "operationId": view_name,
                # Note: We could consider allowing users to pass a description into
                # @api() instead of using the function docstring.
                "description": textwrap.dedent(callback.__doc__ or "").strip(),
                # Tags are useful for grouping operations in codegen
                "tags": [app_name],
                "x-reverse-path": reverse_path,
                "parameters": parameters,
                **request_body,
                "responses": {
                    api_meta.response_status: {
                        "description": "",
                        **api_response,
                    }
                },
            }
        }
    }

    return paths, components


def generate_api_spec(
    urlpatterns: Sequence[URLResolver | URLPattern],
) -> dict[str, Any]:
    """
    Entrypoint for generating an API spec. The function input is a list of URL patterns.
    """

    @dataclasses.dataclass
    class OpenApiOperation:
        callback: Callable[..., HttpResponse]
        name: str
        url: str
        reverse_path: str

    all_urls = get_resolved_url_patterns(urlpatterns)

    operations = []

    # Iterate through all django views within the url patterns and generate specs for
    # them
    for pattern, resolved_url, reverse_path in all_urls:
        if pattern.callback is None:
            continue

        if hasattr(pattern.callback, "_method_router_views"):
            # Special handling for method_router(), which has multiple views on the
            # same URL
            for method, callback in cast(
                dict[str, Callable[..., HttpResponse]],
                pattern.callback._method_router_views,
            ).items():
                if not hasattr(callback, "_api_meta"):
                    logger.debug(
                        "Skipping view %s because it is not using @api decorator",
                        pattern.name,
                    )
                    continue

                api_meta: ApiMeta = callback._api_meta
                assert method == api_meta.method

                operations.append(
                    OpenApiOperation(
                        callback=callback,
                        name=(
                            f"{method.lower()}"
                            "-"
                            f"{pattern.name or pattern.callback.__name__}"
                        ),
                        url=resolved_url,
                        reverse_path=reverse_path,
                    )
                )

        elif hasattr(pattern.callback, "_api_meta"):
            operations.append(
                OpenApiOperation(
                    callback=pattern.callback,
                    name=pattern.name or pattern.callback.__name__,
                    url=resolved_url,
                    reverse_path=reverse_path,
                )
            )

        else:
            logger.debug(
                "Skipping view %s because it is not using @api decorator", pattern.name
            )

    api_paths: dict[str, Any] = {}
    api_components = {}

    for operation in operations:
        paths, components = paths_and_types_for_view(
            view_name=operation.name,
            callback=operation.callback,
            resolved_url=operation.url,
            reverse_path=operation.reverse_path,
        )
        api_components.update(components)

        for path, val in paths.items():
            if path in api_paths:
                # Merge operations that have the same URL but different http methods
                api_paths[path].update(val)
            else:
                api_paths[path] = val

    api_spec = {
        "openapi": "3.1.0",
        "info": {"title": "API overview", "version": "0.0.1"},
        "paths": api_paths,
        "components": {"schemas": api_components},
    }

    logger.info(
        "Generated %s paths and %s schemas", len(api_paths), len(api_components)
    )
    logger.info("%s @api annotated views", len(operations))

    return api_spec
