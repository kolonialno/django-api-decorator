import dataclasses
import functools
import inspect
import logging
import types
import typing
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Protocol, TypedDict

import pydantic
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from pydantic.fields import FieldInfo
from pydantic.fields import _Undefined as PydanticUndefined
from pydantic.functional_validators import BeforeValidator
from pydantic.json import pydantic_encoder

from .type_utils import is_list, is_union
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
        query_params_adapter = _get_query_param_adapter(
            parameters=signature.parameters, query_params=query_params or []
        )

        # If the method has a "body" argument, get a function to call to parse
        # the request body into the type expected by the view.
        body_adapter = None
        if "body" in signature.parameters:
            body_adapter = _get_body_adapter(parameter=signature.parameters["body"])

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
                if _can_have_body(request.method) and body_adapter:
                    extra_kwargs["body"] = body_adapter.validate_json(request.body)

                # Parse query params and add them to the parameters given to the view.
                raw_query_params: dict[str, Any] = {}
                for key in request.GET:
                    print(f"{key}={request.GET.getlist(key)}")
                    if value := request.GET.getlist(key):
                        raw_query_params[key] = value[0] if len(value) == 1 else value
                    else:
                        raw_query_params[key] = True

                query_params = query_params_adapter.validate_python(raw_query_params)
                extra_kwargs.update(query_params.model_dump(exclude_defaults=True))
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
            body_adapter=body_adapter,
            query_params_adapter=query_params_adapter,
        )
        return inner

    return decorator


#######################
# Query param parsing #
#######################


def validate_boolean(value: Any) -> Any:
    return True if value == "" else value


TYPE_MAPPING = {
    bool: Annotated[bool, BeforeValidator(validate_boolean)],
}


def _get_query_param_adapter(
    *,
    parameters: Mapping[str, inspect.Parameter],
    query_params: list[str],
) -> pydantic.TypeAdapter[pydantic.BaseModel]:
    if any(arg_name not in parameters for arg_name in query_params):
        raise TypeError("All parameters specified in query_params must exist")

    fields: dict[str, tuple[Any, FieldInfo]] = {}

    for arg_name in query_params:
        annotation = parameters[arg_name].annotation
        annotation = TYPE_MAPPING.get(annotation, annotation)
        field = pydantic.fields.Field(
            default=(
                parameters[arg_name].default
                if not parameters[arg_name].default == inspect.Parameter.empty
                else PydanticUndefined
            ),
            alias=arg_name.replace("_", "-") if "_" in arg_name else None,
        )
        fields[arg_name] = (annotation, field)

    model = pydantic.create_model("QueryParams", **fields)

    return pydantic.TypeAdapter(model)


################
# Body parsing #
################


def _can_have_body(method: str | None) -> bool:
    return method in ("POST", "PATCH", "PUT")


def _get_body_adapter(*, parameter: inspect.Parameter) -> pydantic.TypeAdapter[Any]:
    annotation = parameter.annotation
    if annotation is inspect.Parameter.empty:
        raise TypeError("The body parameter must have a type annotation")

    return pydantic.TypeAdapter(annotation)


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
