import functools
import inspect
import logging
import typing
from collections.abc import Callable, Mapping
from typing import Annotated, Any, TypedDict

import pydantic
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from pydantic.fields import FieldInfo
from pydantic.functional_validators import BeforeValidator
from pydantic_core import PydanticUndefined

from .types import ApiMeta, FieldError, PublicAPIError
from .utils import get_list_fields, parse_form_encoded_body

P = typing.ParamSpec("P")
T = typing.TypeVar("T")

Annotation = Any
ExceptionHandler = Callable[
    [HttpRequest, ValidationError | pydantic.ValidationError], HttpResponse
]


def api(
    *,
    method: str,
    query_params: list[str] | None = None,
    login_required: bool | None = None,
    response_status: int = 200,
    atomic: bool | None = None,
    auth_check: Callable[[HttpRequest], bool] | None = None,
    serialize_by_alias: bool = False,
    validation_error_handler: ExceptionHandler | None = None,
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

    * serialize_by_alias:
        Is passed as the by_alias argument to TypeAdapter.dump_json(), making
        the model use the aliases defined in model_config when serializing.

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
    validation_error_handler = validation_error_handler or handle_validation_error

    def default_auth_check(request: HttpRequest) -> bool:
        return hasattr(request, "user") and request.user.is_authenticated

    _auth_check = (
        auth_check
        if auth_check is not None
        else getattr(settings, "API_DECORATOR_AUTH_CHECK", default_auth_check)
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., HttpResponse]:
        signature = inspect.signature(func)

        # Get a function that we can call to extract view parameters from
        # the requests query parameters.
        query_params_model = _get_query_params_model(
            parameters=signature.parameters, query_params=query_params or []
        )

        # If the method has a "body" argument, get a function to call to parse
        # the request body into the type expected by the view.
        list_fields, body_adapter = set[str](), None
        if body_annotation := signature.parameters.get("body"):
            list_fields, body_adapter = _get_body_adapter(body_annotation)

        # Get a function to use for encoding the value returned from the view
        # into a request we can return to the client.
        response_adapter = _get_response_adapter(
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
                    if request.content_type in {
                        "application/x-www-form-urlencoded",
                        "multipart/form-data",
                    }:
                        data = parse_form_encoded_body(request, list_fields)
                        extra_kwargs["body"] = body_adapter.validate_python(data)
                    else:
                        extra_kwargs["body"] = body_adapter.validate_json(request.body)

                # Parse query params and add them to the parameters given to the view.
                raw_query_params: dict[str, Any] = {}
                for key in request.GET:
                    if value := request.GET.getlist(key):
                        raw_query_params[key] = value[0] if len(value) == 1 else value
                    else:
                        raw_query_params[key] = True

                query_params = query_params_model.model_validate(raw_query_params)
                extra_kwargs.update(query_params.model_dump(exclude_defaults=True))
            except (
                ValidationError,
                pydantic.ValidationError,
            ) as e:
                # Normalize and return a unified error message payload
                return validation_error_handler(request, e)

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
                return validation_error_handler(request, e)

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

            if not response_adapter:
                raise TypeError(
                    f"{func} is annotated to return an http response, but returned "
                    f"{type(response)}"
                )

            # Encode the response from the view to json and create a response object.
            payload = response_adapter.dump_json(response, by_alias=serialize_by_alias)
            return HttpResponse(
                payload, status=response_status, content_type="application/json"
            )

        inner._api_meta = ApiMeta(  # type: ignore[attr-defined]
            method=method,
            query_params=query_params or [],
            response_status=response_status,
            body_adapter=body_adapter,
            query_params_model=query_params_model,
            response_adapter=response_adapter,
        )
        return inner

    return decorator


#######################
# Query param parsing #
#######################


def validate_boolean(value: Any) -> Any:
    return True if value == "" else value


TYPE_MAPPING = {
    bool: Annotated[bool, BeforeValidator(validate_boolean)],  # type: ignore[call-arg]
}


def _get_query_params_model(
    *,
    parameters: Mapping[str, inspect.Parameter],
    query_params: list[str],
) -> pydantic.BaseModel:
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

    return pydantic.create_model(  # type: ignore[no-any-return,call-overload]
        "QueryParams", **fields
    )


################
# Body parsing #
################


def _can_have_body(method: str | None) -> bool:
    return method in ("POST", "PATCH", "PUT")


def _get_body_adapter(
    parameter: inspect.Parameter,
) -> tuple[set[str], pydantic.TypeAdapter[Any]]:
    annotation = parameter.annotation
    if annotation is inspect.Parameter.empty:
        raise TypeError("The body parameter must have a type annotation")

    list_fields = set()
    if isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
        list_fields = get_list_fields(annotation)

    return list_fields, pydantic.TypeAdapter(annotation)


#####################
# Response encoding #
#####################


def _get_response_adapter(
    *, type_annotation: Annotation
) -> pydantic.TypeAdapter[Any] | None:
    if type_annotation == inspect.Parameter.empty:
        raise TypeError("Missing annotation for return type of api view")
    if type(type_annotation) is type and issubclass(type_annotation, HttpResponse):
        return None
    return pydantic.TypeAdapter(type_annotation)


##################
# Error handling #
##################


class PydanticErrorDict(TypedDict):
    loc: tuple[int | str, ...]
    msg: str


def handle_validation_error(
    request: HttpRequest,
    exception: ValidationError | pydantic.ValidationError,
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
