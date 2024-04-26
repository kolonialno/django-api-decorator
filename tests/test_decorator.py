import datetime
from functools import wraps
from unittest.mock import Mock

import pytest
from django.http import HttpRequest, JsonResponse
from django.test.client import Client
from django.test.utils import override_settings
from django.urls import path
from pydantic import BaseModel
from pytest_mock import MockerFixture

from django_api_decorator.decorators import api

urlpatterns = None


@override_settings(ROOT_URLCONF=__name__)
def test_allowed_methods(client: Client, mocker: MockerFixture) -> None:
    @api(method="GET", login_required=False)
    def get_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"data": True})

    @api(method="POST", login_required=False)
    def post_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"data": True})

    urls = [
        path("get", get_view),
        path("post", post_view),
    ]
    mocker.patch(f"{__name__}.urlpatterns", urls)

    response = client.get("/get")
    assert response.status_code == 200

    response = client.post("/get")
    assert response.status_code == 405

    response = client.get("/post")
    assert response.status_code == 405

    response = client.post("/post")
    assert response.status_code == 200


@override_settings(ROOT_URLCONF=__name__)
def test_login_required(client: Client, mocker: MockerFixture) -> None:
    @api(method="GET", login_required=True, auth_check=lambda request: True)
    def auth_user_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"data": True})

    @api(method="GET", login_required=False, auth_check=lambda request: True)
    def auth_anonymous_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"data": True})

    @api(method="GET", login_required=True, auth_check=lambda request: False)
    def noauth_user_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"data": True})

    @api(method="GET", login_required=False, auth_check=lambda request: False)
    def noauth_anonymous_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"data": True})

    urls = [
        path("auth-user", auth_user_view),
        path("auth-anonymous", auth_anonymous_view),
        path("noauth-user", noauth_user_view),
        path("noauth-anonymous", noauth_anonymous_view),
    ]
    mocker.patch(f"{__name__}.urlpatterns", urls)

    response = client.get("/auth-user")
    assert response.status_code == 200

    response = client.get("/auth-anonymous")
    assert response.status_code == 200

    response = client.get("/noauth-user")
    assert response.status_code == 401

    response = client.get("/noauth-anonymous")
    assert response.status_code == 200


def _create_api_view(view_func, query_params):  # type:ignore
    collector = Mock()

    @api(
        method="GET",
        login_required=False,
        query_params=query_params,
    )
    @wraps(view_func)
    def view(*args, **kwargs):  # type: ignore
        collector(*args, **kwargs)
        view_func(*args, **kwargs)
        return JsonResponse({})

    return collector, view


class TestViews:
    @staticmethod
    def required(r: HttpRequest, query_param: int) -> JsonResponse:
        return JsonResponse({})

    @staticmethod
    def optional(r: HttpRequest, query_param: int = 1) -> JsonResponse:
        return JsonResponse({})

    @staticmethod
    def string(r: HttpRequest, query_param: str) -> JsonResponse:
        return JsonResponse({})

    @staticmethod
    def date(r: HttpRequest, query_param: datetime.date) -> JsonResponse:
        return JsonResponse({})

    @staticmethod
    def number(r: HttpRequest, query_param: int) -> JsonResponse:
        return JsonResponse({})

    @staticmethod
    def boolean(r: HttpRequest, query_param: bool) -> JsonResponse:
        return JsonResponse({})

    @staticmethod
    def path_string(r: HttpRequest, pp: str) -> JsonResponse:
        return JsonResponse({})

    @staticmethod
    def path_int(r: HttpRequest, pp: str) -> JsonResponse:
        return JsonResponse({})

    @staticmethod
    def path_many(r: HttpRequest, pp1: str, pp2: int) -> JsonResponse:
        return JsonResponse({})


@pytest.mark.parametrize(
    "view,have_url,want_status,want_values",
    [
        (TestViews.required, "/?query-param=1", 200, {"query_param": 1}),
        (TestViews.required, "/?query_param=1", 400, None),
        (TestViews.required, "/", 400, None),
        (TestViews.optional, "/?query-param=2", 200, {"query_param": 2}),
        (TestViews.optional, "/", 200, {}),
        (TestViews.string, "/?query-param=abc", 200, {"query_param": "abc"}),
        (
            TestViews.date,
            "/?query-param=2020-01-01",
            200,
            {"query_param": datetime.date(2020, 1, 1)},
        ),
        (TestViews.date, "/?query-param=2020", 400, None),
        (TestViews.number, "/?query-param=100", 200, {"query_param": 100}),
        (TestViews.number, "/?query-param=abc", 400, None),
        (TestViews.boolean, "/?query-param=true", 200, {"query_param": True}),
        (TestViews.boolean, "/?query-param=True", 200, {"query_param": True}),
        (TestViews.boolean, "/?query-param=yes", 200, {"query_param": True}),
        (TestViews.boolean, "/?query-param=on", 200, {"query_param": True}),
        (TestViews.boolean, "/?query-param=1", 200, {"query_param": True}),
        (TestViews.boolean, "/?query-param", 200, {"query_param": True}),
        (TestViews.boolean, "/?query-param=false", 200, {"query_param": False}),
        (TestViews.boolean, "/?query-param=off", 200, {"query_param": False}),
        (TestViews.boolean, "/?query-param=0", 200, {"query_param": False}),
    ],
)
def test_query_params(  # type: ignore
    mocker, client, settings, view, have_url, want_status, want_values
):
    collector, api_view = _create_api_view(view, ["query_param"])  # type: ignore
    urls = [path("", api_view)]
    settings.ROOT_URLCONF = __name__
    mocker.patch(f"{__name__}.urlpatterns", urls)

    got = client.get(have_url)
    assert got.status_code == want_status
    if want_values is None:
        collector.assert_not_called()
    else:
        collector.assert_called_once_with(mocker.ANY, **want_values)


@pytest.mark.parametrize(
    "view,path_spec,have_url,want_status,want_values",
    [
        (TestViews.path_string, "<str:pp>", "/hello", 200, {"pp": "hello"}),
        (TestViews.path_string, "<str:pp>", "/", 404, None),
        (TestViews.path_int, "<int:pp>", "/1", 200, {"pp": 1}),
        (TestViews.path_int, "<int:pp>", "/h", 404, None),
        (
            TestViews.path_many,
            "<str:pp1>/<int:pp2>",
            "/hello/33",
            200,
            {"pp1": "hello", "pp2": 33},
        ),
    ],
)
def test_path_params(  # type: ignore
    mocker, client, settings, view, path_spec, have_url, want_status, want_values
):
    """
    Tests URL paths with the decorator. The decorator doesn't touch the parameters
    currently, so we are essentially testing Django internals, but it is good to have
    this check in case we start altering params.
    """

    collector, api_view = _create_api_view(view, None)  # type: ignore
    urls = [path(path_spec, api_view)]
    settings.ROOT_URLCONF = __name__
    mocker.patch(f"{__name__}.urlpatterns", urls)

    got = client.get(have_url)

    assert got.status_code == want_status
    if want_values is None:
        collector.assert_not_called()
    else:
        collector.assert_called_once_with(mocker.ANY, **want_values)


@override_settings(ROOT_URLCONF=__name__)
def test_basic_parsing(client: Client, mocker: MockerFixture) -> None:
    class Body(BaseModel):
        pass

    @api(
        method="POST",
        login_required=False,
    )
    def view(request: HttpRequest, body: Body) -> JsonResponse:
        return JsonResponse({})

    urls = [path("", view)]
    mocker.patch(f"{__name__}.urlpatterns", urls)

    # Allow empty body with empty type
    assert client.post("/").status_code == 200
    assert client.post("/", data={}).status_code == 200
    # Allow empty dict JSON as well
    assert client.post("/", data={}, content_type="application/json").status_code == 200


@override_settings(ROOT_URLCONF=__name__)
def test_parsing_error_propagation(client: Client, mocker: MockerFixture) -> None:
    class Body(BaseModel):
        num: int
        d: datetime.date

    @api(
        method="POST",
        login_required=False,
    )
    def view(request: HttpRequest, body: Body) -> JsonResponse:
        return JsonResponse({})

    urls = [path("", view)]
    mocker.patch(f"{__name__}.urlpatterns", urls)

    assert client.post("/", data={}, content_type="application/json").status_code == 400
    assert (
        client.post(
            "/", data={"num": 3, "d": "2022-01-01"}, content_type="application/json"
        ).status_code
        == 200
    )
    # Check that field errors propagate
    response = client.post(
        "/", data={"num": "x", "d": "2022-01-01"}, content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["field_errors"].keys() == {"num"}

    response = client.post(
        "/", data={"num": "x", "d": "2022-31-41"}, content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["field_errors"].keys() == {"num", "d"}


@override_settings(ROOT_URLCONF=__name__)
def test_parsing_form_encoded(client: Client, mocker: MockerFixture) -> None:
    class Body(BaseModel):
        num: int
        d: datetime.date

    @api(
        method="POST",
        login_required=False,
    )
    def view(request: HttpRequest, body: Body) -> JsonResponse:
        return JsonResponse(body.model_dump(mode="json"))

    urls = [path("", view)]
    mocker.patch(f"{__name__}.urlpatterns", urls)

    # Test missing fields
    response = client.post("/", data={})
    assert response.status_code == 400
    assert response.json() == {
        "errors": ["num: Field required", "d: Field required"],
        "field_errors": {
            "num": {"code": "missing", "message": "Field required"},
            "d": {"code": "missing", "message": "Field required"},
        },
    }

    response = client.post("/", data={"num": 3, "d": "2022-01-01"})
    assert response.status_code == 200
    assert response.json() == {"num": 3, "d": "2022-01-01"}

    # Check that field errors propagate
    response = client.post("/", data={"num": "x", "d": "2022-01-01"})
    assert response.status_code == 400
    assert response.json() == {
        "errors": [
            "num: Input should be a valid integer, "
            "unable to parse string as an integer"
        ],
        "field_errors": {
            "num": {
                "code": "int_parsing",
                "message": "Input should be a valid integer, "
                "unable to parse string as an integer",
            }
        },
    }

    response = client.post("/", data={"num": 1, "d": "2022-31-41"})
    assert response.status_code == 400
    assert response.json() == {
        "errors": [
            "d: Input should be a valid date or datetime, "
            "month value is outside expected range of 1-12"
        ],
        "field_errors": {
            "d": {
                "code": "date_from_datetime_parsing",
                "message": (
                    "Input should be a valid date or datetime, "
                    "month value is outside expected range of 1-12"
                ),
            }
        },
    }


@override_settings(ROOT_URLCONF=__name__)
def test_parsing_list(client: Client, mocker: MockerFixture) -> None:
    class Body(BaseModel):
        num: int
        d: datetime.date

    @api(
        method="POST",
        login_required=False,
    )
    def view(request: HttpRequest, body: list[Body]) -> JsonResponse:
        return JsonResponse({})

    urls = [path("", view)]
    mocker.patch(f"{__name__}.urlpatterns", urls)

    assert client.post("/", data={}, content_type="application/json").status_code == 400

    assert (
        client.post(
            "/",
            data=[],
            content_type="application/json",
        ).status_code
        == 200
    )

    assert (
        client.post(
            "/",
            data=[{"num": 3, "d": "2022-01-01"}],
            content_type="application/json",
        ).status_code
        == 200
    )
    # Check that field errors propagate. Only errors from the first element
    # are shown.
    response = client.post(
        "/",
        data=[{"num": "x", "d": "2022-01-01"}, {"num": "x", "d": "2022-31-41"}],
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["field_errors"].keys() == {"0.num", "1.num", "1.d"}


@override_settings(ROOT_URLCONF=__name__)
def test_custom_exception_handler(client: Client, mocker: MockerFixture) -> None:
    """
    Test that a custom validation error handler is called
    """

    def handle_exception(request: HttpRequest, e: Exception) -> JsonResponse:
        return JsonResponse({"error": "Something is wrong here"}, status=400)

    class Body(BaseModel):
        num: int
        d: datetime.date

    @api(
        method="POST",
        login_required=False,
        validation_error_handler=handle_exception,
    )
    def view(request: HttpRequest, body: list[Body]) -> JsonResponse:
        return JsonResponse({})

    urls = [
        path("", view),
    ]

    mocker.patch(f"{__name__}.urlpatterns", urls)

    response = client.post("/", data={}, content_type="application/json")
    assert response.status_code == 400
    assert response.json() == {"error": "Something is wrong here"}
