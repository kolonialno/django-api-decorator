import pytest
from django.db import DEFAULT_DB_ALIAS, transaction
from django.http import HttpRequest, JsonResponse
from django.test.client import Client
from django.test.utils import override_settings
from django.urls import path
from pydantic import BaseModel
from pytest_mock import MockerFixture

from django_api_decorator.decorators import api
from django_api_decorator.utils import method_router

urlpatterns = None


@override_settings(ROOT_URLCONF=__name__)
def test_allowed_methods(client: Client, mocker: MockerFixture) -> None:
    @api(method="GET", login_required=False)
    def get_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"data": True})

    class Body(BaseModel):
        name: str

    @api(method="POST", login_required=False)
    def post_view(request: HttpRequest, body: Body) -> JsonResponse:
        return JsonResponse({"data": True})

    urls = [
        path(
            "api",
            method_router(
                GET=get_view,
                POST=post_view,
            ),
        ),
    ]

    mocker.patch(f"{__name__}.urlpatterns", urls)

    response = client.get("/api")
    assert response.status_code == 200

    response = client.post("/api", data={"name": "x"}, content_type="application/json")
    assert response.status_code == 200

    response = client.put("/api")
    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, POST"


def test_non_atomic_requests_propagated_from_api_views() -> None:
    @api(method="GET")
    def get_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({})

    @api(method="POST")
    def post_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({})

    view = method_router(GET=get_view, POST=post_view)

    assert view._non_atomic_requests == {DEFAULT_DB_ALIAS}  # type: ignore[attr-defined]


def test_non_atomic_requests_not_propagated_from_plain_views() -> None:
    """
    A plain view expects to run inside the ATOMIC_REQUESTS transaction, so the
    router cannot be exempt from it even if the other views are.
    """

    @api(method="GET")
    def get_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({})

    def post_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({})

    view = method_router(GET=get_view, POST=post_view)

    assert view._non_atomic_requests == set()  # type: ignore[attr-defined]


@pytest.mark.django_db(transaction=True)
@override_settings(ROOT_URLCONF=__name__)
def test_atomic_requests_opt_out_is_kept(client: Client, mocker: MockerFixture) -> None:
    """
    The GET assertion is the one that catches the router dropping the marker. The
    POST one is there to show that views that do want a transaction still get one.
    """

    @api(method="GET", atomic=False)
    def non_atomic_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"atomic": transaction.get_connection().in_atomic_block})

    @api(method="POST", atomic=True)
    def atomic_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"atomic": transaction.get_connection().in_atomic_block})

    urls = [
        path("api", method_router(GET=non_atomic_view, POST=atomic_view)),
    ]

    mocker.patch(f"{__name__}.urlpatterns", urls)

    assert client.get("/api").json() == {"atomic": False}
    assert client.post("/api").json() == {"atomic": True}
