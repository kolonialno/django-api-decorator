import pytest
from django.http import HttpRequest
from django.test.client import Client
from django.test.utils import override_settings
from django.urls import path

from django_api_decorator.decorators import api
from django_api_decorator.schema_file import get_api_spec


@api(method="GET")
def view(
    request: HttpRequest,
) -> None:
    return None


urlpatterns = [
    path("view", view, name="view_name"),
]


@override_settings(
    ROOT_URLCONF=__name__,
    API_DECORATOR_SCHEMA_IGNORED_RESOLVERS=[("test", "test")],
)
def test_get_api_spec_deprecated_filter(client: Client) -> None:
    with pytest.deprecated_call():
        get_api_spec()
