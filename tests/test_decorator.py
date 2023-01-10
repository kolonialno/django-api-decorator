import datetime
from unittest import mock

from django.http import JsonResponse
from django.test.utils import override_settings
from django.urls import path
from pydantic import BaseModel

from django_api_decorator.decorators import api

urlpatterns = None


@override_settings(ROOT_URLCONF=__name__)
def test_allowed_methods(client):
    @api(method="GET", login_required=False)
    def get_view(request):
        return JsonResponse({"data": True})

    @api(method="POST", login_required=False)
    def post_view(request):
        return JsonResponse({"data": True})

    urls = [
        path("get", get_view),
        path("post", post_view),
    ]

    with mock.patch(f"{__name__}.urlpatterns", urls):
        response = client.get("/get")
        assert response.status_code == 200

        response = client.post("/get")
        assert response.status_code == 405

        response = client.get("/post")
        assert response.status_code == 405

        response = client.post("/post")
        assert response.status_code == 200


@override_settings(ROOT_URLCONF=__name__)
def test_login_required(client):
    @api(method="GET", login_required=True, auth_check=lambda request: True)
    def auth_user_view(request):
        return JsonResponse({"data": True})

    @api(method="GET", login_required=False, auth_check=lambda request: True)
    def auth_anonymous_view(request):
        return JsonResponse({"data": True})

    @api(method="GET", login_required=True, auth_check=lambda request: False)
    def noauth_user_view(request):
        return JsonResponse({"data": True})

    @api(method="GET", login_required=False, auth_check=lambda request: False)
    def noauth_anonymous_view(request):
        return JsonResponse({"data": True})

    urls = [
        path("auth-user", auth_user_view),
        path("auth-anonymous", auth_anonymous_view),
        path("noauth-user", noauth_user_view),
        path("noauth-anonymous", noauth_anonymous_view),
    ]

    with mock.patch(f"{__name__}.urlpatterns", urls):
        response = client.get("/auth-user")
        assert response.status_code == 200

        response = client.get("/auth-anonymous")
        assert response.status_code == 200

        response = client.get("/noauth-user")
        assert response.status_code == 401

        response = client.get("/noauth-anonymous")
        assert response.status_code == 200


@override_settings(ROOT_URLCONF=__name__)
def test_url_path(client):
    """
    Tests URL paths with the decorator. The decorator doesn't touch the parameters
    currently, so we are essentially testing Django internals, but it is good to have
    this check in case we start altering params.
    """

    @api(method="GET", login_required=False)
    def view(request, a: int, b: str):
        return JsonResponse({"a": a, "b": b})

    urls = [
        path("<int:a>/<str:b>", view),
    ]

    with mock.patch(f"{__name__}.urlpatterns", urls):
        response = client.get("/33/test")
        assert response.status_code == 200
        assert response.json() == {
            "a": 33,
            "b": "test",
        }

        response = client.get("/33a/test")
        assert response.status_code == 404


@override_settings(ROOT_URLCONF=__name__)
def test_url_path_and_query(client):
    @api(
        method="GET",
        login_required=False,
        query_params=[
            "num",
            "opt_num",
            "date",
            "opt_date",
            "string",
            "opt_string",
            "boolean",
            "opt_boolean",
        ],
    )
    def view(
        request,
        a: int,
        b: str,
        num: int,
        date: datetime.date,
        string: str,
        boolean: bool,
        opt_num: int | None = None,
        opt_date: datetime.date | None = None,
        opt_string: str | None = None,
        opt_boolean: bool | None = None,
    ):
        return JsonResponse({})

    urls = [
        path("<int:a>/<str:b>", view),
    ]

    with mock.patch(f"{__name__}.urlpatterns", urls):
        assert client.get("/33/test").status_code == 400
        assert (
            client.get(
                "/33/test?num=3&date=2020-01-01&string=abc&boolean=false"
            ).status_code
            == 200
        )
        # Include some optional values
        assert (
            client.get(
                "/33/test?num=3&date=2020-01-01&string=abc&boolean=false&opt_num=1"
                "&opt_date=2022-01-01"
            ).status_code
            == 200
        )
        # Include all optional values
        assert (
            client.get(
                "/33/test?num=3&date=2020-01-01&string=abc&boolean=false&opt_num=1"
                "&opt_date=2022-01-01"
                "&opt_string=123&opt_boolean=1"
            ).status_code
            == 200
        )
        # Include only optional values but no required
        assert (
            client.get(
                "/33/test?opt_num=1&opt_date=2022-01-01&opt_string=123&opt_boolean=1"
            ).status_code
            == 400
        )
        # Invalid path
        assert (
            client.get(
                "/a33/test?num=3&date=2020-01-01&string=abc&boolean=false"
            ).status_code
            == 404
        )
        # Invalid number
        assert (
            client.get(
                "/33/test?num=3x&date=2020-01-01&string=abc&boolean=false"
            ).status_code
            == 400
        )
        # Invalid date
        assert (
            client.get(
                "/33/test?num=3&date=2020-31-31&string=abc&boolean=false"
            ).status_code
            == 400
        )
        # Invalid bool
        assert (
            client.get("/33/test?num=3&date=2020-01-01&string=&boolean=xyz").status_code
            == 400
        )


@override_settings(ROOT_URLCONF=__name__)
def test_basic_parsing(client):
    class Body(BaseModel):
        pass

    @api(
        method="POST",
        login_required=False,
    )
    def view(request, body: Body):
        return JsonResponse({})

    urls = [
        path("", view),
    ]

    with mock.patch(f"{__name__}.urlpatterns", urls):
        # No data is invalid
        assert client.post("/").status_code == 400
        # No content_type is invalid
        assert client.post("/", data={}).status_code == 400
        # Json content type is ok
        assert (
            client.post("/", data={}, content_type="application/json").status_code
            == 200
        )


@override_settings(ROOT_URLCONF=__name__)
def test_parsing_error_propagation(client):
    class Body(BaseModel):
        num: int
        d: datetime.date

    @api(
        method="POST",
        login_required=False,
    )
    def view(request, body: Body):
        return JsonResponse({})

    urls = [
        path("", view),
    ]

    with mock.patch(f"{__name__}.urlpatterns", urls):
        assert (
            client.post("/", data={}, content_type="application/json").status_code
            == 400
        )
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
def test_parsing_list(client):
    class Body(BaseModel):
        num: int
        d: datetime.date

    @api(
        method="POST",
        login_required=False,
    )
    def view(request, body: list[Body]):
        return JsonResponse({})

    urls = [
        path("", view),
    ]

    with mock.patch(f"{__name__}.urlpatterns", urls):
        assert (
            client.post("/", data={}, content_type="application/json").status_code
            == 400
        )

        # Empty list is not a valid payload
        assert (
            client.post(
                "/",
                data=[],
                content_type="application/json",
            ).status_code
            == 400
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
        assert response.json()["field_errors"].keys() == {"num"}
