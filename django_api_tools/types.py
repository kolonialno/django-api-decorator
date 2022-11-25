from dataclasses import dataclass
from typing import TypedDict


class FieldError(TypedDict):
    message: str
    code: str | None


@dataclass
class ApiMeta:
    """
    Dataclass used on @api decorated views to preserve some information that cannot be inferred when inspecting the view.
    """

    method: str
    query_params: list[str]
    response_status: int


class PublicAPIError(Exception):
    """
    Exception for public facing errors.
    Raises an ApiException in the frontend.
    """

    def __init__(
        self,
        *args,
        status_code: int | None = 500,
        message: str | None = "",
        errors: dict | None = None,
        **kwargs,
    ):
        super().__init__(*args, *kwargs)

        self.message = errors if errors is not None else [message]
        self.status_code = status_code
