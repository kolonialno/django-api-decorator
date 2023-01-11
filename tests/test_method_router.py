from unittest import mock

from django.http import HttpRequest, JsonResponse
from django.test.client import Client
from django.test.utils import override_settings
from django.urls import path
from pydantic import BaseModel

from django_api_decorator.decorators import api
from django_api_decorator.utils import method_router

urlpatterns = None


@override_settings(ROOT_URLCONF=__name__)
def test_allowed_methods(client: Client) -> None:
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

    with mock.patch(f"{__name__}.urlpatterns", urls):
        response = client.get("/api")
        assert response.status_code == 200

        response = client.post("/api")
        assert response.status_code == 200

        response = client.put("/api")
        assert response.status_code == 405
        assert response.headers["Allow"] == "GET, POST"
