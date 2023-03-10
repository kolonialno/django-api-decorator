import dataclasses
from typing import Any, Union

import pydantic
import pytest
from django.http.response import HttpResponse

from django_api_decorator.decorators import (
    _dataclass_encoder,
    _get_response_encoder,
    _json_encoder,
    _pydantic_encoder,
)


def test_get_response_encoder_any() -> None:
    assert _get_response_encoder(type_annotation=Any) == _json_encoder


def test_get_response_encoder_dict() -> None:
    assert _get_response_encoder(type_annotation=dict) == _json_encoder


def test_get_response_encoder_pydantic_model() -> None:
    class PydanticRecord(pydantic.BaseModel):
        pass

    assert _get_response_encoder(type_annotation=PydanticRecord) == _pydantic_encoder


def test_get_response_encoder_dataclass() -> None:
    @dataclasses.dataclass
    class DataclassRecord:
        pass

    assert _get_response_encoder(type_annotation=DataclassRecord) == _dataclass_encoder


def test_get_response_encoder_http_response() -> None:
    response_encoder = _get_response_encoder(type_annotation=HttpResponse)
    assert callable(response_encoder)
    assert response_encoder.__name__ == "<lambda>"  # type: ignore[attr-defined]


def test_get_response_encoder_list_of_dicts() -> None:
    assert (
        _get_response_encoder(type_annotation=list[dict])  # type: ignore
        == _json_encoder
    )
    assert _get_response_encoder(type_annotation=list[dict[str, Any]]) == _json_encoder


def test_get_response_encoder_union_of_str_int_bool() -> None:
    assert _get_response_encoder(type_annotation=Union[str, int, bool]) == _json_encoder
    assert _get_response_encoder(type_annotation=str | int | bool) == _json_encoder


def test_get_response_encoder_list_of_pydantic_records() -> None:
    class PydanticRecord(pydantic.BaseModel):
        pass

    assert (
        _get_response_encoder(type_annotation=list[PydanticRecord]) == _pydantic_encoder
    )


def test_get_response_encoder_list_of_dataclasses() -> None:
    @dataclasses.dataclass
    class DataclassRecord:
        pass

    with pytest.raises(NotImplementedError):
        _get_response_encoder(type_annotation=list[DataclassRecord])


def test_get_response_encoder_union_of_pydantic_records() -> None:
    class PydanticRecord(pydantic.BaseModel):
        pass

    class PydanticTwoRecord(pydantic.BaseModel):
        pass

    assert (
        _get_response_encoder(type_annotation=Union[PydanticRecord, PydanticTwoRecord])
        == _pydantic_encoder
    )


def test_get_response_encoder_union_of_pydantic_and_dict() -> None:
    class PydanticRecord(pydantic.BaseModel):
        pass

    with pytest.raises(NotImplementedError):
        _get_response_encoder(type_annotation=Union[PydanticRecord, dict])


def test_get_response_encoder_union_of_pydantic_and_dataclass() -> None:
    class PydanticRecord(pydantic.BaseModel):
        pass

    @dataclasses.dataclass
    class DataclassRecord:
        pass

    with pytest.raises(NotImplementedError):
        _get_response_encoder(type_annotation=Union[PydanticRecord, DataclassRecord])
