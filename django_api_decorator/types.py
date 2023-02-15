from dataclasses import dataclass
from typing import Any, TypedDict


class FieldError(TypedDict):
    message: str
    code: str | None


@dataclass
class ApiMeta:
    """
    Dataclass used on @api decorated views to preserve some information that cannot
    be inferred when inspecting the view.
    """

    method: str
    query_params: list[str]
    response_status: int


class PublicAPIError(Exception):
    """
    Exception for public facing errors.
    Raises an ApiException in the frontend.

    Args:
        status_code (int | None, optional): HTTP status code. Defaults to 500.
        message (str | None, optional): Public facing error message. Defaults to "".
        errors (dict[str, Any] | None, optional): Underlying error messages. Defaults to None.
    """

    def __init__(
        self,
        *args: Any,
        status_code: int | None = 500,
        message: str | None = "",
        errors: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, *kwargs)

        self.message = errors if errors is not None and not message else message
        self.status_code = status_code
