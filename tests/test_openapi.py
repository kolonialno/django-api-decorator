import datetime
from enum import Enum
from unittest import mock

from django.http import JsonResponse
from django.test.utils import override_settings
from django.urls import path
from django_api_tools.decorators import api
from django_api_tools.openapi import generate_api_spec
from pydantic import BaseModel

urlpatterns = None


@override_settings(ROOT_URLCONF=__name__)
def test_openapi_spec(client):
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
        request,
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
        path("<str:path_str>/<int:path_int>", view),
    ]

    assert generate_api_spec(urls) == {
        "openapi": "3.0.0",
        "info": {"title": "API overview", "version": "0.0.1"},
        "paths": {
            "/{path_str}/{path_int}": {
                "post": {
                    "operationId": "view",
                    "description": "",
                    "tags": ["test_openapi"],
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
                            "schema": {"type": "integer"},
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
                            "schema": {"type": "string", "format": "date"},
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
                            "schema": {"type": "string"},
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
                            "schema": {"type": "boolean"},
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
                    "description": "An enumeration.",
                    "enum": [1, 2],
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
                        "d": {"title": "D", "type": "string", "format": "date"},
                    },
                    "required": ["name", "num"],
                },
            }
        },
    }


@override_settings(ROOT_URLCONF=__name__)
def test_return_type_union(client):
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
    def view(
        request,
    ) -> A | B | C:
        return C(ok=True)

    urls = [
        path("", view),
    ]

    assert generate_api_spec(urls) == {
        "openapi": "3.0.0",
        "info": {"title": "API overview", "version": "0.0.1"},
        "paths": {
            "/": {
                "get": {
                    "operationId": "view",
                    "description": "",
                    "tags": ["test_openapi"],
                    "parameters": [],
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "oneOf": [
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
