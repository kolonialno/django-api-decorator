import random
import re

import pytest
from django.http import HttpRequest, JsonResponse
from django.test.client import Client
from django.urls import path
from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict

from django_api_decorator.decorators import api
from django_api_decorator.openapi import generate_api_spec


class MyTypedDict(TypedDict):
    an_integer: int


class MyPydanticModel(BaseModel):
    an_integer: int


def camel_case(string: str) -> str:
    """
    Convert string from snake_case to camelCase
    """

    _pascal_case = re.sub(r"(?:^|_)(.)", lambda m: m.group(1).upper(), string)
    return _pascal_case[0].lower() + _pascal_case[1:]


class MyCamelCasePydanticModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=camel_case,
        populate_by_name=True,
    )

    an_integer: int


@api(method="GET")
def view_json_response(r: HttpRequest) -> JsonResponse:
    return JsonResponse({"an_integer": 1})


@api(method="GET")
def view_typed_dict(r: HttpRequest) -> MyTypedDict:
    return {"an_integer": 1}


@api(method="GET")
def view_int(r: HttpRequest) -> int:
    return 1


@api(method="GET")
def view_bool(r: HttpRequest) -> bool:
    return False


@api(method="GET")
def view_pydantic_model(r: HttpRequest) -> MyPydanticModel:
    return MyPydanticModel(an_integer=1)


@api(method="GET", serialize_by_alias=True)
def view_camel_case_pydantic_model(r: HttpRequest) -> MyCamelCasePydanticModel:
    return MyCamelCasePydanticModel(an_integer=1)


@api(method="GET")
def view_union(r: HttpRequest) -> int | str:
    return random.choice([1, "foo"])  # type: ignore[return-value]


urlpatterns = [
    path("json-response", view_json_response),
    path("typed-dict", view_typed_dict),
    path("int", view_int),
    path("bool", view_bool),
    path("pydantic-model", view_pydantic_model),
    path("pydantic-camel-case-model", view_camel_case_pydantic_model),
    path("union", view_union),
]


@pytest.mark.parametrize(
    "url,expected_response",
    [
        ("/json-response", b'{"an_integer": 1}'),
        ("/typed-dict", b'{"an_integer":1}'),
        ("/int", b"1"),
        ("/bool", b"false"),
        ("/pydantic-model", b'{"an_integer":1}'),
        ("/pydantic-camel-case-model", b'{"anInteger":1}'),
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
        "openapi": "3.1.0",
        "info": {"title": "API overview", "version": "0.0.1"},
        "paths": {
            "/union": {
                "get": {
                    "operationId": "view_union",
                    "description": "",
                    "tags": ["test_response_encoding"],
                    "x-reverse-path": "",
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
            "/pydantic-camel-case-model": {
                "get": {
                    "operationId": "view_camel_case_pydantic_model",
                    "description": "",
                    "tags": ["test_response_encoding"],
                    "x-reverse-path": "",
                    "parameters": [],
                    "responses": {
                        200: {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/MyCamelCasePydanticModel"  # noqa: E501
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
                    "x-reverse-path": "",
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
                    "x-reverse-path": "",
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
                    "x-reverse-path": "",
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
                    "x-reverse-path": "",
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
                    "x-reverse-path": "",
                    "parameters": [],
                    "responses": {200: {"description": ""}},
                }
            },
        },
        "components": {
            "schemas": {
                "MyCamelCasePydanticModel": {
                    "properties": {
                        "anInteger": {"title": "Aninteger", "type": "integer"}
                    },
                    "required": ["anInteger"],
                    "title": "MyCamelCasePydanticModel",
                    "type": "object",
                },
                "MyPydanticModel": {
                    "properties": {
                        "an_integer": {"title": "An Integer", "type": "integer"}
                    },
                    "required": ["an_integer"],
                    "title": "MyPydanticModel",
                    "type": "object",
                },
                "MyTypedDict": {
                    "properties": {
                        "an_integer": {"title": "An Integer", "type": "integer"}
                    },
                    "required": ["an_integer"],
                    "title": "MyTypedDict",
                    "type": "object",
                },
            }
        },
    }
