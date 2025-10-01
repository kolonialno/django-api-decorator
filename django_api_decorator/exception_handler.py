import functools
from typing import Any, Callable, Generic, Protocol, Type, TypeAlias, TypedDict, TypeVar

from django_stubs_ext import StrOrPromise
from typing_extensions import Unpack

from django_api_decorator.types import PublicAPIError

E = TypeVar("E", bound=Exception)


class APIError(Protocol):
    def __call__(
        self,
        *args: Any,
        status_code: int | None,
        message: str | None,
        errors: dict[str, Any] | None,
        **kwargs: Any,
    ) -> Exception: ...


class APIErrorArgs(TypedDict):
    status_code: int | None
    message: str | None
    errors: dict[str, Any] | None


Message = str | dict[str, Any] | None | StrOrPromise
Callback = Callable[[E], Exception]


class NormalHandlerKwarg(TypedDict):
    message: Message | None
    status_code: int | None


class CallbackHandlerKwarg(TypedDict, Generic[E]):
    callback: Callback[E]


Options: TypeAlias = Unpack[NormalHandlerKwarg] | Unpack[CallbackHandlerKwarg]  # type: ignore # noqa: E501
Args: TypeAlias = Unpack[tuple[Message, int | None]] | Unpack[tuple[Callback]]  # type: ignore # noqa: E501

_ExceptionHandlerMessage: TypeAlias = tuple[Type[Exception], Message]
_ExceptionHandlerStatus: TypeAlias = tuple[Type[Exception], int]
_ExceptionHandlerMessageStatus: TypeAlias = tuple[Type[Exception], Message, int]
_ExceptionHandlerCallback: TypeAlias = tuple[Type[Exception], Callback[E]]

ExceptionHandler: TypeAlias = (
    _ExceptionHandlerMessage
    | _ExceptionHandlerStatus
    | _ExceptionHandlerMessageStatus
    | _ExceptionHandlerCallback[E]
)


def create_exception_handler(
    exc: Type[E],
    *args: Args,
    exception_cls: APIError = PublicAPIError,
    **options: Options,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Create an exception handler for which catches a specific exception and returns it
    as a APIError with provided message.

    Best suited to handling a single exception. If you want to handle multiple without
    chaining decorators, you can use the create_exception_handlers instead.

    Accepted parameters is either:
    - message: a message containing info about the error that just occurred. Defaults to
               exception message, but None has to be passed as an arg.
    - status_code: an HTTP status code. Defaults to 400 - Bad request.

    Or:
    - callback: a callback callable that takes the exception instance as a
                single parameter and returns a APIError.

    """

    def _get_arg_index(index: int, default: Any | None = None) -> Any:
        try:
            return args[index]
        except IndexError:
            return default

    message: str | Message = options.get("message", None) or _get_arg_index(0)
    status_code: int = options.get("status_code", None) or _get_arg_index(1)

    callback: Callable[..., Any] = options.get("callback", None) or _get_arg_index(0)

    handler: ExceptionHandler[E] | None = None

    # _ExceptionHandlerMessageStatus
    if message is not None and status_code is not None:
        handler = (exc, message, status_code)

    # _ExceptionHandlerCallback
    elif message is None and status_code is None and callback is not None:
        handler = (exc, callback)

    # _ExceptionHandlerStatus
    elif message is None and status_code is not None:
        handler = (exc, status_code)

    # _ExceptionHandlerMessage
    elif status_code is None:
        handler = (exc, message)

    return create_exception_handlers((handler,), exception_cls=exception_cls)


def create_exception_handlers(
    handlers: tuple[ExceptionHandler[E], ...],
    *,
    exception_cls: APIError = PublicAPIError,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Create a series of exception handlers for which catches an exception in passed
    series and returns it as a APIError with provided message.

    Best suited for a series of exceptions to avoid repetition. If handling a one-off,
    it's recommended to use the create_exception_handler instead.

    A handler can either be a list of:
    - exception type: the exception type. E.g. just reference, not instantiated object.
    - message: a message containing info about the error that just occurred. Defaults to
               exception message, but None has to be passed as an arg.
    - status_code: an HTTP status code. Defaults to 400 - Bad request.

    Or:
    - exception type: the exception type. E.g. just reference, not instantiated object.
    - callback: a callback callable that takes the exception instance as a
                single parameter and returns a APIError.


    """
    exceptions = tuple(handler[0] for handler in handlers)

    def decorator(func: Any) -> Callable[..., Any]:
        @functools.wraps(func)
        def inner(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                handler = next(
                    (handler for handler in handlers if isinstance(e, handler[0])), None
                )

                if handler is None or len(handler) < 2:
                    raise e

                # Defaults to 400 and error message by original exception.
                status_code = 400
                message = str(e)

                if len(handler) == 2:
                    arg = handler[1]

                    # _ExceptionHandlerMessage
                    if isinstance(arg, str) or hasattr(arg, "__str__"):
                        _exc, message = handler  # type: ignore

                    # _ExceptionHandlerStatus
                    elif isinstance(arg, int):
                        _exc, status_code = handler  # type: ignore

                    # _ExceptionHandlerCallback
                    elif callable(arg):
                        _exc, callback = handler  # type:ignore
                        raise callback(e) from e  # type: ignore

                # _ExceptionHandlerMessageStatus
                elif len(handler) == 3:
                    _exc, message, status_code = handler  # type: ignore
                else:
                    raise e

                error: APIErrorArgs = {
                    "errors": message if isinstance(message, dict) else None,
                    "message": message if not isinstance(message, dict) else None,
                    "status_code": status_code,
                }

                raise exception_cls(**error) from e

        return inner

    return decorator
