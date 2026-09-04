import pytest
from django.http import HttpRequest
from django.test.client import RequestFactory
from django.urls import path

from django_api_decorator.decorators import api
from django_api_decorator.openapi import generate_api_spec

# These views are called directly rather than through the Django test client:
# the client runs conditional_content_removal(), which strips the body from
# 1xx/204/304 responses, hiding whether the decorator wrote one.


@api(method="DELETE", response_status=204)
def view_no_content(request: HttpRequest) -> None:
    return None


@api(method="DELETE", response_status=304)
def view_not_modified(request: HttpRequest) -> None:
    return None


@api(method="GET")
def view_none_with_content_allowed(request: HttpRequest) -> None:
    return None


@pytest.mark.parametrize(
    "view,status",
    [
        (view_no_content, 204),
        (view_not_modified, 304),
    ],
)
def test_status_without_content_gets_no_body(view: object, status: int) -> None:
    """
    A 1xx, 204 or 304 carries no content, so the return value must not be
    encoded into a body: the response would be malformed.
    """
    response = view(RequestFactory().delete("/"))  # type: ignore[operator]

    assert response.status_code == status
    assert response.content == b""
    # Generated clients choose how to parse an empty response from the content
    # type, so it stays what it has always been.
    assert response["Content-Type"] == "application/json"


def test_none_is_still_encoded_when_content_is_allowed() -> None:
    """A status that allows content keeps encoding the return value, None included."""
    response = view_none_with_content_allowed(RequestFactory().get("/"))

    assert response.status_code == 200
    assert response.content == b"null"


def test_schema_advertises_no_content_for_bodyless_status() -> None:
    """The spec must not describe a body for a status that cannot carry one."""
    spec = generate_api_spec([path("no-content", view_no_content)])

    assert "content" not in spec["paths"]["/no-content"]["delete"]["responses"][204]
