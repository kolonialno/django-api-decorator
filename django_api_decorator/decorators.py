import dataclasses
import datetime
import functools
import inspect
import json
import logging
import types
import typing
from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypedDict, cast

import pydantic
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from pydantic.json import pydantic_encoder

from .type_utils import (
    is_list,
    is_optional,
    is_union,
    unwrap_list_item_type,
    unwrap_optional,
)
from .types import ApiMeta, FieldError, PublicAPIError

P = typing.ParamSpec("P")
T = typing.TypeVar("T")

Annotation = Any


def api(
    *,
    method: str,
    query_params: list[str] | None = None,
    login_required: bool | None = None,
    response_status: int = 200,
    atomic: bool | None = None,
    auth_check: Callable[[HttpRequest], bool] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, HttpResponse]]:
    """
    Defines an API view. This handles validation of query parameters, parsing of
    the request body, access control, and serialization of the response payload.

    * query_params:
        This is a list of the function parameters that should be
        exposed as query parameters. The parameters must have type
        annotations and underscores are replaced with dashes.

    * login_required:
        Indicates that this endpoint is only available to authenticated
        users. Non-authenticated users will get a 401 response.

    * response_status:
        HTTP status code to use if the view _does not_ return an
        Response object, but rather just the data we should return.

    The request body parsing is done by inspecting the view parameter types. If
    the view has a body parameter, we will try to decode the payload to that
    type. Currently Django Rest Framework serializers and pydantic models are are
     supported.

    Similarly the response body is encoded based on the type annotation for the
    return type. If the view is type annotated to return an HttpResponse object
    nothing is done to that response. In all other case the returned object is
    attempted to be encoded to JSON.
    """

    login_required = (
        login_required
        if login_required is not None
        else getattr(settings, "API_DECORATOR_DEFAULT_LOGIN_REQUIRED", True)
    )
    atomic = (
        atomic
        if atomic is not None
        else getattr(settings, "API_DECORATOR_DEFAULT_ATOMIC", True)
    )

    def default_auth_check(request: HttpRequest) -> bool:
        return request.user.is_authenticated

    _auth_check = (
        auth_check
        if auth_check is not None
        else getattr(settings, "API_DECORATOR_AUTH_CHECK", default_auth_check)
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., HttpResponse]:
        signature = inspect.signature(func)

        # Get a function that we can call to extract view parameters from
        # the requests query parameters.
        parse_query_params = _get_query_param_parser(
            parameters=signature.parameters, query_params=query_params or []
        )

        # If the method has a "body" argument, get a function to call to parse
        # the request body into the type expected by the view.
        body_parser: BodyParser | None = None
        if "body" in signature.parameters:
            body_parser = _get_body_parser(parameter=signature.parameters["body"])

        # Get a function to use for encoding the value returned from the view
        # into a request we can return to the client.
        response_encoder = _get_response_encoder(
            type_annotation=signature.return_annotation
        )

        @functools.wraps(func)
        @transaction.non_atomic_requests()
        @require_http_methods([method])
        def inner(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            # Check if the view requires the user to be logged in and if so make
            # sure the user is actually logged in.
            if login_required and not _auth_check(request):
                return JsonResponse({"errors": ["Login required"]}, status=401)

            try:
                extra_kwargs = {}

                # Parse the request body if the request method allows a body and the
                # view has requested that we should parse the body.
                if _can_have_body(request.method) and body_parser:
                    extra_kwargs["body"] = body_parser(request=request)

                # Parse query params and add them to the parameters given to the view.
                extra_kwargs.update(parse_query_params(request))
            except (
                ValidationError,
                pydantic.ValidationError,
            ) as e:
                # Normalize and return a unified error message payload
                return handle_validation_error(exception=e)

            try:
                if atomic:
                    with transaction.atomic():
                        response = func(request, *args, **kwargs, **extra_kwargs)
                else:
                    response = func(request, *args, **kwargs, **extra_kwargs)
            except (ObjectDoesNotExist, Http404):
                # Return a simple 404 error if we catch an "x does not exist" exception
                return JsonResponse(
                    {"errors": ["The resource you tried to access does not exist"]},
                    status=404,
                )
            except ValidationError as e:
                # Normalize and return a unified error message payload, but only
                # for Django's ValidationError error, not DRF or Pydantic
                return handle_validation_error(exception=e)

            except PublicAPIError as exc:
                # Raised custom errors to frontend
                return JsonResponse(
                    {"errors": exc.message},
                    status=exc.status_code,
                )
            except Exception:
                logger = logging.getLogger(f"{func.__module__}.{func.__name__}")
                logger.exception(
                    "Internal server error",
                )
                return JsonResponse(
                    {"errors": ["Internal server error"]},
                    status=500,
                )

            # If the view returned an HttpRequest object, return that directly.
            # This can happen anytime regardless of what the view is typed to
            # return because of CSRF protections, that is called before the view
            # and may return an HttpResponse immediately without calling the view.
            if isinstance(response, HttpResponse):
                return response

            # Encode the response from the view to json and create a response object.
            return response_encoder(payload=response, status=response_status)

        inner._api_meta = ApiMeta(  # type: ignore[attr-defined]
            method=method,
            query_params=query_params or [],
            response_status=response_status,
        )
        return inner

    return decorator


#######################
# Query param parsing #
#######################


class Validator(Protocol):
    def __call__(self, value: str, *, query_param_name: str) -> Any:
        ...


class _missing:
    """Marker for missing query parameters"""


def _validate_int(value: str, *, query_param_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{query_param_name} must be an integer")


def _validate_bool(value: str, *, query_param_name: str) -> bool:
    value = value.lower().strip()

    if value in ("", "yes", "on", "true", "1"):
        return True

    if value in ("no", "off", "false", "0"):
        return False

    raise ValidationError(f"{query_param_name} must be a boolean")


def _validate_date(value: str, *, query_param_name: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{query_param_name} must be a valid date")


def _get_validator(parameter: inspect.Parameter) -> Validator:
    annotation = parameter.annotation
    if annotation is inspect.Parameter.empty:
        raise ValueError(
            f"Parameter {parameter.name} specified as a query param must have a"
            f" type annotation."
        )

    param_is_optional = is_optional(annotation)

    if param_is_optional and parameter.default is inspect.Parameter.empty:
        raise ValueError(
            f"Parameter {parameter.name} specified as an optional param must have a"
            f" default value."
        )

    if annotation is str or (param_is_optional and unwrap_optional(annotation) is str):
        return lambda value, query_param_name: value

    if annotation is int or (param_is_optional and unwrap_optional(annotation) is int):
        return _validate_int

    if annotation is datetime.date or (
        param_is_optional and unwrap_optional(annotation) is datetime.date
    ):
        return _validate_date

    if annotation is bool or (
        param_is_optional and unwrap_optional(annotation) is bool
    ):
        return _validate_bool

    raise ValueError(
        f"Unsupported type annotation for query param {parameter.name}: {annotation}"
    )


def _get_query_param_parser(
    *,
    parameters: Mapping[str, inspect.Parameter],
    query_params: list[str],
) -> Callable[[HttpRequest], Mapping[str, Any]]:
    query_param_mapping = (
        {query_param.replace("_", "-"): query_param for query_param in query_params}
        if query_params
        else {}
    )
    query_param_validators = {
        query_param: _get_validator(parameters[arg_name])
        for query_param, arg_name in query_param_mapping.items()
    }
    required_params = {
        arg_name
        for query_param, arg_name in query_param_mapping.items()
        if parameters[arg_name].default is inspect.Parameter.empty
    }

    def parser(request: HttpRequest) -> Mapping[str, Any]:
        validated = {}

        for query_param, arg_name in query_param_mapping.items():
            validator = query_param_validators[query_param]
            value = request.GET.get(query_param, _missing)

            # If the argument is required, make sure it has a value
            if value is _missing:
                if arg_name in required_params:
                    raise ValidationError(
                        f"Query parameter {query_param} must be specified"
                    )
            else:
                validated[arg_name] = validator(
                    cast(str, value), query_param_name=query_param
                )

        return validated

    return parser


################
# Body parsing #
################


class BodyParser(Protocol):
    def __call__(self, *, request: HttpRequest) -> Any:
        ...


def _can_have_body(method: str | None) -> bool:
    return method in ("POST", "PATCH", "PUT")


def _get_body_parser(*, parameter: inspect.Parameter) -> BodyParser:
    annotation = parameter.annotation
    if annotation is inspect.Parameter.empty:
        raise TypeError("The body parameter must have a type annotation")

    body_is_list = is_list(type_annotation=annotation)
    if body_is_list:
        annotation = unwrap_list_item_type(type_annotation=annotation)

    if issubclass(annotation, pydantic.BaseModel):
        return _pydantic_parser(model_cls=annotation, body_is_list=body_is_list)

    raise ValueError(
        f"Annotation for body parameter must be a django-rest-framework or pydantic "
        f"serializer class, the current type annotation is: {annotation}"
    )


def _pydantic_parser(
    *, model_cls: type[pydantic.BaseModel], body_is_list: bool
) -> BodyParser:
    def parser(
        *, request: HttpRequest
    ) -> pydantic.BaseModel | list[pydantic.BaseModel]:
        try:
            data = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            raise ValidationError("Invalid JSON") from e

        if body_is_list:
            if not isinstance(data, list):
                raise ValidationError("Expected request body to be a list")

            if not len(data):
                raise ValidationError("Empty list not allowed")

            result = []
            for i, element in enumerate(data):
                if not isinstance(element, dict):
                    raise ValidationError(f"Expected list element {i} to be an object")

                result.append(model_cls(**element))
            return result

        else:
            if not isinstance(data, dict):
                raise ValidationError("Expected request body to be an object")

            instance = model_cls(**data)
            return instance

    return parser


#####################
# Response encoding #
#####################


class ResponseEncoder(Protocol):
    def __call__(self, *, payload: Any, status: int) -> HttpResponse:
        ...


def _is_class(*, type_annotation: Annotation) -> bool:
    return inspect.isclass(type_annotation) and (
        type(type_annotation)
        is not types.GenericAlias  # type: ignore[comparison-overlap]
    )


def _get_response_encoder(*, type_annotation: Annotation) -> ResponseEncoder:
    type_is_class = _is_class(type_annotation=type_annotation)

    if type_is_class and issubclass(type_annotation, HttpResponse):
        return lambda payload, status: payload

    if dataclasses.is_dataclass(type_annotation):
        return _dataclass_encoder

    if type_is_class and issubclass(type_annotation, pydantic.BaseModel):
        return _pydantic_encoder

    # We need to unwrap inner list and union annotations
    # to verify whether we support them.
    inner_type_annotations: tuple[type, ...] = tuple()

    type_is_list = is_list(type_annotation=type_annotation)
    type_is_union = is_union(type_annotation=type_annotation)

    if type_is_list or type_is_union:
        inner_type_annotations = typing.get_args(type_annotation)

    if inner_type_annotations and all(
        _is_class(type_annotation=t) for t in inner_type_annotations
    ):
        # Pydantic encoder supports both list and Union wrappers
        if all(issubclass(t, pydantic.BaseModel) for t in inner_type_annotations):
            return _pydantic_encoder

        if any(issubclass(t, pydantic.BaseModel) for t in inner_type_annotations):
            raise NotImplementedError(
                "@api: We only support all values being pydantic models in a union"
            )

        if any(dataclasses.is_dataclass(t) for t in inner_type_annotations):
            raise NotImplementedError(
                "@api: We do not support encoding dataclasses inside lists or unions"
            )

    # Assume any other response can be JSON encoded. We might want to restrict
    # this to some verified types 🤔
    return _json_encoder


def _json_encoder(*, payload: Any, status: int) -> HttpResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"default": pydantic_encoder},
        safe=False,
    )


def _pydantic_encoder(payload: Any, status: int) -> HttpResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"default": pydantic_encoder},
        safe=False,
    )


def _dataclass_encoder(*, payload: Any, status: int) -> HttpResponse:
    data = dataclasses.asdict(payload)
    return _json_encoder(payload=data, status=status)


##################
# Error handling #
##################


class PydanticErrorDict(TypedDict):
    loc: tuple[int | str, ...]
    msg: str


def handle_validation_error(
    *,
    exception: (ValidationError | pydantic.ValidationError),
) -> HttpResponse:
    errors: list[str]
    field_errors: Mapping[str, FieldError]

    if isinstance(exception, pydantic.ValidationError):

        def error_loc(loc: tuple[int | str, ...]) -> str:
            return ".".join(map(str, loc))

        def error_str(err: PydanticErrorDict) -> str:
            return f"{error_loc(err['loc'])}: {err['msg']}"

        errors = [error_str(err) for err in exception.errors()]
        try:
            field_errors = {
                error_loc(err["loc"]): {
                    "message": err["msg"],
                    "code": err["type"],
                }
                for err in exception.errors()
            }
        except AttributeError:
            field_errors = {}

    elif isinstance(exception, ValidationError):
        errors = exception.messages
        try:
            field_errors = {
                key: {
                    "message": e[0].messages[0],
                    "code": getattr(e[0], "code", None),
                }
                for key, e in exception.error_dict.items()
            }
        except (AttributeError, IndexError):
            field_errors = {}
    elif isinstance(exception.detail, list):
        errors = [str(message) for message in exception.detail]
        field_errors = {}
    elif isinstance(exception.detail, str):
        errors = [exception.detail]
        field_errors = {}
    else:
        errors = [str(message) for message in exception.detail.values()]
        field_errors = {
            key: {"message": str(message), "code": message.code}
            for key, message in exception.detail.items()
        }

    return JsonResponse({"errors": errors, "field_errors": field_errors}, status=400)
