import random

import pytest
from django.http import HttpRequest, JsonResponse
from django.test.client import Client
from django.urls import path
from pydantic import BaseModel
from typing_extensions import TypedDict

from django_api_decorator.decorators import api
from django_api_decorator.openapi import generate_api_spec


class MyTypedDict(TypedDict):
    a: int


class MyPydanticModel(BaseModel):
    a: int


@api(method="GET")
def view_json_response(r: HttpRequest) -> JsonResponse:
    return JsonResponse({"a": 1})


@api(method="GET")
def view_typed_dict(r: HttpRequest) -> MyTypedDict:
    return {"a": 1}


@api(method="GET")
def view_int(r: HttpRequest) -> int:
    return 1


@api(method="GET")
def view_bool(r: HttpRequest) -> bool:
    return False


@api(method="GET")
def view_pydantic_model(r: HttpRequest) -> MyPydanticModel:
    return MyPydanticModel(a=1)


@api(method="GET")
def view_union(r: HttpRequest) -> int | str:
    return random.choice([1, "foo"])  # type: ignore[return-value]


urlpatterns = [
    path("json-response", view_json_response),
    path("typed-dict", view_typed_dict),
    path("int", view_int),
    path("bool", view_bool),
    path("pydantic-model", view_pydantic_model),
    path("union", view_union),
]


@pytest.mark.parametrize(
    "url,expected_response",
    [
        ("/json-response", b'{"a": 1}'),
        ("/typed-dict", b'{"a":1}'),
        ("/int", b"1"),
        ("/bool", b"false"),
        ("/pydantic-model", b'{"a":1}'),
    ],
)
@pytest.mark.urls(__name__)
def test_response_encoding(url: str, expected_response: bytes, client: Client) -> None:
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == expected_response


def test_schema() -> None:
    spec = generate_api_spec(urlpatterns)
    assert spec == {
        "openapi": "3.0.0",
        "info": {"title": "API overview", "version": "0.0.1"},
        "paths": {
            "/union": {
                "get": {
                    "operationId": "view_union",
                    "description": "",
                    "tags": ["test_response_encoding"],
                    "parameters": [],
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "anyOf": [
                                            {"type": "integer"},
                                            {"type": "string"},
                                        ]
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/pydantic-model": {
                "get": {
                    "operationId": "view_pydantic_model",
                    "description": "",
                    "tags": ["test_response_encoding"],
                    "parameters": [],
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/MyPydanticModel"
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/bool": {
                "get": {
                    "operationId": "view_bool",
                    "description": "",
                    "tags": ["test_response_encoding"],
                    "parameters": [],
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {"schema": {"type": "boolean"}}
                            },
                        }
                    },
                }
            },
            "/int": {
                "get": {
                    "operationId": "view_int",
                    "description": "",
                    "tags": ["test_response_encoding"],
                    "parameters": [],
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {"schema": {"type": "integer"}}
                            },
                        }
                    },
                }
            },
            "/typed-dict": {
                "get": {
                    "operationId": "view_typed_dict",
                    "description": "",
                    "tags": ["test_response_encoding"],
                    "parameters": [],
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/MyTypedDict"
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/json-response": {
                "get": {
                    "operationId": "view_json_response",
                    "description": "",
                    "tags": ["test_response_encoding"],
                    "parameters": [],
                    "responses": {200: {"description": ""}},
                }
            },
        },
        "components": {
            "schemas": {
                "MyPydanticModel": {
                    "properties": {"a": {"title": "A", "type": "integer"}},
                    "required": ["a"],
                    "title": "MyPydanticModel",
                    "type": "object",
                },
                "MyTypedDict": {
                    "properties": {"a": {"title": "A", "type": "integer"}},
                    "required": ["a"],
                    "title": "MyTypedDict",
                    "type": "object",
                },
            }
        },
    }
