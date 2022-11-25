import dataclasses
import inspect
import logging
import re
import typing
from collections.abc import Callable, Sequence
from datetime import date
from typing import TYPE_CHECKING, Any, Union, cast

import pydantic
import pydantic.schema
from django.urls.resolvers import RoutePattern, URLPattern, URLResolver
from pydantic import BaseModel
from pydantic.utils import get_model

from .type_utils import (
    get_inner_list_type,
    is_optional,
    is_pydantic_model,
    is_union,
    unwrap_optional,
)
from .types import ApiMeta

if TYPE_CHECKING:
    from pydantic.dataclasses import Dataclass

logger = logging.getLogger(__name__)

schema_ref = "#/components/schemas/{model}"


def is_type_supported(t: type) -> bool:
    """
    Controls whether or not we support the provided type as request body or response data.
    """

    try:
        return is_pydantic_model(t)
    except TypeError:
        return False


def name_for_type(t: type) -> str:
    """
    Returns OpenAPI schema for the provided type.
    """

    assert is_type_supported(t)

    # normalize_name removes special characters like [] from generics.
    # get_model gets the pydantic model, even if a pydantic dataclass is used.

    return pydantic.schema.normalize_name(get_model(t).__name__)


def schema_type_ref(t: type, *, is_list: bool = False) -> dict[str, Any]:
    """
    Returns a openapi reference to the provided type, and optionally wraps it in an array
    """

    reference = {"$ref": schema_ref.format(model=name_for_type(t))}

    if is_list:
        return {
            "type": "array",
            "items": reference,
        }

    return reference


def get_resolved_url_patterns(
    base_patterns: Sequence[URLResolver | URLPattern],
) -> list[tuple[URLPattern, str]]:
    """
    Given a list of base URL patterns, this function digs down into the URL hierarchy and evaluates the full URLs of all
    django views that have a simple path (e.g. no regex).
    Returns a list of tuples with each RoutePattern and its full URL.
    """

    unresolved_patterns: list[tuple[URLResolver | URLPattern, str]] = [
        (url_pattern, "/") for url_pattern in base_patterns
    ]
    resolved_urls: list[tuple[URLPattern, str]] = []

    while len(unresolved_patterns):
        url_pattern, url_prefix = unresolved_patterns.pop()

        if not isinstance(url_pattern.pattern, RoutePattern):
            logger.debug("Skipping URL that is not simple (e.g. regex or locale url)")
            continue

        # RoutePattern.__str__ returns the actual url pattern
        url = url_prefix + str(url_pattern.pattern)

        # If we are dealing with a URL Resolver we should dig further down.
        if isinstance(url_pattern, URLResolver):
            unresolved_patterns += [
                (child_pattern, url) for child_pattern in url_pattern.url_patterns
            ]
        else:
            resolved_urls.append((url_pattern, url))

    return resolved_urls


def django_path_to_openapi_url_and_parameters(path: str) -> tuple[str, list[dict]]:
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

    def replacer(match: re.Match) -> str:
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

    # Replaces e.g. "/x/<str:hello>/<int:hi>/" with "/x/{hello}/{hi}/" and also populates the parameters variable.
    path = re.sub(r"<([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)>", replacer, path)

    return path, parameters


def get_schema_for_type_annotation(
    input_type_annotation: type,
) -> tuple[dict | None, list[type]]:
    """
    Helper function that generates a OpenAPI schema based on an input_type_annotation
    Supports pydantic models directly, or with Union / list wrappers.
    """

    type_is_union = is_union(type_annotation=input_type_annotation)
    if type_is_union:
        type_annotations = typing.get_args(input_type_annotation)
    else:
        type_annotations = (input_type_annotation,)

    # List of schemas we generate based on the return types (to support oneOf union types)
    schemas = []
    inner_type_annotations = []

    for t in type_annotations:
        type_annotation, type_is_list = get_inner_list_type(t)
        if type_annotation is not None and is_type_supported(type_annotation):
            schemas.append(schema_type_ref(type_annotation, is_list=type_is_list))
            inner_type_annotations.append(type_annotation)
        else:
            # If one of the type's are not supported, skip the view
            return None, []

    if type_is_union and len(schemas) > 0:
        return {"oneOf": schemas}, inner_type_annotations

    if len(schemas) == 1:
        return schemas[0], inner_type_annotations

    return None, []


def paths_and_types_for_view(
    *, view_name: str, callback: Callable, resolved_url: str
) -> tuple[dict, list[type]]:

    api_meta: ApiMeta | None = getattr(callback, "_api_meta", None)

    assert api_meta is not None

    signature = inspect.signature(callback)

    # Types that should be included in the schema object (referenced via schema_type_ref)
    types: list[type] = []

    schema, return_types = get_schema_for_type_annotation(signature.return_annotation)

    if schema:
        types += return_types
        api_response = {"content": {"application/json": {"schema": schema}}}
    else:
        api_response = {}
        logger.debug(
            "Return type of %s (%s) unsupported: %s",
            resolved_url,
            view_name,
            signature.return_annotation,
        )

    additional_data = {}

    if "body" in signature.parameters:
        body_schema, body_return_types = get_schema_for_type_annotation(
            signature.parameters["body"].annotation
        )
        if body_schema:
            types += body_return_types
            additional_data = {
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": body_schema}},
                }
            }
        else:
            logger.debug(
                "Body type of %s (%s) unsupported: %s",
                resolved_url,
                view_name,
                signature.parameters["body"].annotation,
            )

    path, url_parameters = django_path_to_openapi_url_and_parameters(resolved_url)

    query_parameters = openapi_query_parameters(
        query_params=api_meta.query_params, signature=signature
    )

    # Assuming standard django folder structure with [project name]/[app name]/....
    app_name = callback.__module__.split(".")[1]

    paths = {
        path: {
            api_meta.method.lower(): {
                "operationId": view_name,
                # Note: We could consider allowing users to pass a description into @api() instead of using the
                # function docstring.
                "description": callback.__doc__ or "",
                # Tags are useful for grouping operations in codegen
                "tags": [app_name],
                "parameters": url_parameters + query_parameters,
                **additional_data,
                "responses": {
                    api_meta.response_status: {
                        "description": "",
                        **api_response,  # type: ignore
                    }
                },
            }
        }
    }

    return paths, types


def openapi_query_parameters(
    *, query_params: list[str], signature: inspect.Signature
) -> list[dict]:
    """
    Converts a function signature and a list of query params into openapi query parameters.
    """

    parameters = []
    for query_param in query_params:
        query_url_name = query_param.replace("_", "-")

        parameter = signature.parameters[query_param]

        annotation = parameter.annotation
        has_default = parameter.default != inspect.Parameter.empty

        param_is_optional = is_optional(annotation)
        if param_is_optional:
            annotation = unwrap_optional(annotation)

        schema = None

        if annotation is str:
            schema = {"type": "string"}

        if annotation is int:
            schema = {"type": "integer"}

        if annotation is date:
            schema = {"type": "string", "format": "date"}

        if annotation is bool:
            schema = {"type": "boolean"}

        if schema is None:
            logger.warning(
                "Could not generate types for query param %s with type %s.",
                query_url_name,
                annotation,
            )
            continue

        parameters.append(
            {
                "name": query_url_name,
                "in": "query",
                "required": not (param_is_optional or has_default),
                "schema": schema,
            }
        )

    return parameters


def schemas_for_types(api_types: list[type]) -> dict:

    # This only supports Pydantic models for now.
    assert all(
        hasattr(t, "__pydantic_model__") or issubclass(t, BaseModel) for t in api_types
    )

    return pydantic.schema.schema(
        cast(Sequence[Union[type[BaseModel], type["Dataclass"]]], api_types),
        ref_template=schema_ref,
    )["definitions"]


def generate_api_spec(urlpatterns: Sequence[URLResolver | URLPattern]) -> dict:
    """
    Entrypoint for generating an API spec. The function input is a list of URL patterns.
    """

    @dataclasses.dataclass
    class OpenApiOperation:
        callback: Callable
        name: str
        url: str

    all_urls = get_resolved_url_patterns(urlpatterns)

    operations = []

    # Iterate through all django views within the url patterns and generate specs for them
    for pattern, resolved_url in all_urls:
        if pattern.callback is None:
            continue

        if hasattr(pattern.callback, "_method_router_views"):
            # Special handling for method_router(), which has multiple views on the same URL
            for method, callback in cast(
                dict[str, Callable], pattern.callback._method_router_views  # type: ignore
            ).items():

                if not hasattr(callback, "_api_meta"):
                    logger.debug(
                        "Skipping view %s because it is not using @api decorator",
                        pattern.name,
                    )
                    continue

                api_meta: ApiMeta = callback._api_meta  # type: ignore
                assert method == api_meta.method

                operations.append(
                    OpenApiOperation(
                        callback=callback,
                        name=f"{method.lower()}-{pattern.name or pattern.callback.__name__}",
                        url=resolved_url,
                    )
                )

        elif hasattr(pattern.callback, "_api_meta"):
            operations.append(
                OpenApiOperation(
                    callback=pattern.callback,
                    name=pattern.name or pattern.callback.__name__,
                    url=resolved_url,
                )
            )

        else:
            logger.debug(
                "Skipping view %s because it is not using @api decorator", pattern.name
            )

    api_paths: dict[str, Any] = {}
    api_types = []

    for operation in operations:

        paths, types = paths_and_types_for_view(
            view_name=operation.name,
            callback=operation.callback,
            resolved_url=operation.url,
        )
        api_types += types

        for path, val in paths.items():
            if path in api_paths:
                # Merge operations that have the same URL but different http methods
                api_paths[path].update(val)
            else:
                api_paths[path] = val

    api_schemas = schemas_for_types(api_types)

    api_spec = {
        "openapi": "3.0.0",
        "info": {"title": "API overview", "version": "0.0.1"},
        "paths": api_paths,
        "components": {"schemas": api_schemas},
    }

    logger.info("Generated %s paths and %s schemas", len(api_paths), len(api_schemas))
    logger.info("%s @api annotated views", len(operations))

    return api_spec
