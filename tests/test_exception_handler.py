import pytest
from django_api_decorator.types import PublicAPIError

from django_api_decorator.exception_handler import (
    create_exception_handler,
    create_exception_handlers,
)


class CustomException(Exception):
    def __init__(
        self,
        message: str,
        additional_info: str | None = None,
    ):
        super().__init__(message)
        self.additional_info = additional_info


@pytest.mark.parametrize(
    "message, expected",
    (
        (None, ["A testing exception"]),
        ("Custom error message", ["Custom error message"]),
        (
            {
                "error1": "Some message for error 1",
                "error2": "Some message for error 2",
            },
            {
                "error1": "Some message for error 1",
                "error2": "Some message for error 2",
            },
        ),
    ),
)
def test_create_exception_handler_args(message, expected):
    """
    Test that the exception handler decorator is able to catch provided exception
    and return a PublicAPIError instead with provided message when provided with args
    as options.
    """

    @create_exception_handler(CustomException, message, 401)
    def test_func():
        raise CustomException(message="A testing exception")

    with pytest.raises(PublicAPIError) as exc_info:
        test_func()

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == expected


@pytest.mark.parametrize(
    "message, expected",
    (
        ("Custom error message", ["Custom error message"]),
        (
            {
                "error1": "Some message for error 1",
                "error2": "Some message for error 2",
            },
            {
                "error1": "Some message for error 1",
                "error2": "Some message for error 2",
            },
        ),
    ),
)
def test_create_exception_handler_kwargs(message, expected):
    """
    Test that the exception handler decorator is able to catch provided exception
    and return a PublicAPIError instead with provided message when provided with
    kwargs as options.
    """

    @create_exception_handler(CustomException, message=message, status_code=401)
    def test_func():
        raise CustomException(message="A testing exception")

    with pytest.raises(PublicAPIError) as exc_info:
        test_func()

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == expected


def test_create_exception_handler_with_callback():
    """
    Test that the exception handler decorator is able to catch provided exception
    and run callback.
    """

    def callback_func(exc: CustomException):
        message = {"error": str(exc), "info": exc.additional_info}
        return PublicAPIError(status_code=500, errors=message)

    @create_exception_handler(CustomException, callback=callback_func)
    def test_func():
        raise CustomException(
            message="A testing exception", additional_info="Some additional info"
        )

    with pytest.raises(PublicAPIError) as exc_info:
        test_func()

    assert exc_info.value.status_code == 500
    assert exc_info.value.message == {
        "error": "A testing exception",
        "info": "Some additional info",
    }


def test_create_exception_handlers():
    def callback_func1(exc: CustomException):
        message = {"error": str(exc), "info": exc.additional_info}
        return PublicAPIError(status_code=500, errors=message)

    handlers = (
        (CustomException, callback_func1),
        (TypeError, "Custom error message", 401),
        (ValueError, "A value error"),
        (RuntimeError, None),
    )

    @create_exception_handlers(handlers)
    def test_func1():
        raise CustomException(
            message="A testing exception", additional_info="Some additional info"
        )

    with pytest.raises(PublicAPIError) as exc_info1:
        test_func1()

    assert exc_info1.value.status_code == 500
    assert exc_info1.value.message == {
        "error": "A testing exception",
        "info": "Some additional info",
    }

    @create_exception_handlers(handlers)
    def test_func2():
        raise TypeError("A testing exception")

    with pytest.raises(PublicAPIError) as exc_info2:
        test_func2()

    assert exc_info2.value.status_code == 401
    assert exc_info2.value.message == ["Custom error message"]

    @create_exception_handlers(handlers)
    def test_func3():
        raise ValueError("Some value error")

    with pytest.raises(PublicAPIError) as exc_info3:
        test_func3()

    assert exc_info3.value.status_code == 400
    assert exc_info3.value.message == ["A value error"]

    @create_exception_handlers(handlers)
    def test_func4():
        raise RuntimeError("Default exception message")

    with pytest.raises(PublicAPIError) as exc_info4:
        test_func4()

    assert exc_info4.value.status_code == 400
    assert exc_info4.value.message == ["Default exception message"]
