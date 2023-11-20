import datetime
from enum import Enum

from django.http import HttpRequest
from django.test.client import Client
from django.test.utils import override_settings
from django.urls import URLPattern, URLResolver, path
from django.urls.resolvers import RoutePattern
from pydantic import BaseModel

from django_api_decorator.decorators import api
from django_api_decorator.openapi import generate_api_spec, get_resolved_url_patterns

urlpatterns = None


@override_settings(ROOT_URLCONF=__name__)
def test_openapi_spec(client: Client) -> None:
    class Body(BaseModel):
        name: str
        num: int
        d: datetime.date | None

    class State(Enum):
        OK = 1
        FAIL = 2

    class Response(BaseModel):
        state: State
        num: int

    @api(
        method="POST",
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
        request: HttpRequest,
        body: Body,
        path_str: str,
        path_int: int,
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
    ) -> Response:
        return Response(state=State.OK, num=3)

    urls = [
        path("<str:path_str>/<int:path_int>", view, name="view_name"),
    ]

    assert generate_api_spec(urls) == {
        "openapi": "3.1.0",
        "info": {"title": "API overview", "version": "0.0.1"},
        "paths": {
            "/{path_str}/{path_int}": {
                "post": {
                    "operationId": "view_name",
                    "description": "",
                    "tags": ["test_openapi"],
                    "x-reverse-path": "view_name",
                    "parameters": [
                        {
                            "name": "path_str",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "path_int",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        },
                        {
                            "name": "num",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer"},
                        },
                        {
                            "name": "opt-num",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "anyOf": [{"type": "integer"}, {"type": "null"}],
                                "default": None,
                            },
                        },
                        {
                            "name": "date",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "format": "date"},
                        },
                        {
                            "name": "opt-date",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "anyOf": [
                                    {"type": "string", "format": "date"},
                                    {"type": "null"},
                                ],
                                "default": None,
                            },
                        },
                        {
                            "name": "string",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "opt-string",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "default": None,
                            },
                        },
                        {
                            "name": "boolean",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "boolean"},
                        },
                        {
                            "name": "opt-boolean",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                                "default": None,
                            },
                        },
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Body"}
                            }
                        },
                    },
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Response"}
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "State": {
                    "title": "State",
                    "enum": [1, 2],
                    "type": "integer",
                },
                "Response": {
                    "title": "Response",
                    "type": "object",
                    "properties": {
                        "state": {"$ref": "#/components/schemas/State"},
                        "num": {"title": "Num", "type": "integer"},
                    },
                    "required": ["state", "num"],
                },
                "Body": {
                    "title": "Body",
                    "type": "object",
                    "properties": {
                        "name": {"title": "Name", "type": "string"},
                        "num": {"title": "Num", "type": "integer"},
                        "d": {
                            "title": "D",
                            "anyOf": [
                                {"type": "string", "format": "date"},
                                {"type": "null"},
                            ],
                        },
                    },
                    "required": ["name", "num", "d"],
                },
            }
        },
    }


@override_settings(ROOT_URLCONF=__name__)
def test_return_type_union(client: Client) -> None:
    class A(BaseModel):
        name: str

    class B(BaseModel):
        num: int

    class C(BaseModel):
        ok: bool

    @api(
        method="GET",
        login_required=False,
    )
    def view(request: HttpRequest) -> A | B | C:
        return C(ok=True)

    urls = [
        path("", view),
    ]

    assert generate_api_spec(urls) == {
        "openapi": "3.1.0",
        "info": {"title": "API overview", "version": "0.0.1"},
        "paths": {
            "/": {
                "get": {
                    "operationId": "view",
                    "description": "",
                    "tags": ["test_openapi"],
                    "x-reverse-path": "",
                    "parameters": [],
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "anyOf": [
                                            {"$ref": "#/components/schemas/A"},
                                            {"$ref": "#/components/schemas/B"},
                                            {"$ref": "#/components/schemas/C"},
                                        ]
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "A": {
                    "title": "A",
                    "type": "object",
                    "properties": {"name": {"title": "Name", "type": "string"}},
                    "required": ["name"],
                },
                "B": {
                    "title": "B",
                    "type": "object",
                    "properties": {"num": {"title": "Num", "type": "integer"}},
                    "required": ["num"],
                },
                "C": {
                    "title": "C",
                    "type": "object",
                    "properties": {"ok": {"title": "Ok", "type": "boolean"}},
                    "required": ["ok"],
                },
            }
        },
    }


def test_get_resolved_url_patterns():
    child_pattern = URLPattern(
        RoutePattern("child_pattern/nested/deep/"), lambda x: x, name="child_view"
    )

    base_patterns = [
        URLResolver(
            pattern=RoutePattern("toplevel_pattern/"),
            urlconf_name=[
                child_pattern,
            ],
            namespace="top_namespace",
        )
    ]

    result = get_resolved_url_patterns(base_patterns)
    assert result == [
        (
            child_pattern,
            "/toplevel_pattern/child_pattern/nested/deep/",
            "top_namespace:child_view",
        )
    ]
