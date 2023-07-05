import types
import typing

import pydantic


def is_dict(*, type_annotation: type) -> bool:
    return typing.get_origin(type_annotation) is dict


def is_any(*, type_annotation: type) -> bool:
    return getattr(type_annotation, "_name", None) == "Any"


def is_union(*, type_annotation: type) -> bool:
    return typing.get_origin(type_annotation) in (
        types.UnionType,  # PEP 604 union type expressions
        typing.Union,  # Old-style explicit unions
    )


def is_optional(type_annotation: type) -> bool:
    return is_union(
        type_annotation=type_annotation
    ) and types.NoneType in typing.get_args(type_annotation)


def unwrap_optional(type_annotation: type) -> type:
    return next(  # type: ignore[no-any-return]
        arg
        for arg in typing.get_args(type_annotation)
        if not issubclass(arg, types.NoneType)
    )


def is_list(*, type_annotation: type) -> bool:
    return typing.get_origin(type_annotation) is list


def unwrap_list_item_type(*, type_annotation: type) -> type:
    return typing.get_args(type_annotation)[0]  # type: ignore[no-any-return]


def get_inner_list_type(type_annotation: type) -> tuple[type, bool]:
    type_is_list = is_list(type_annotation=type_annotation)
    if type_is_list:
        type_annotation = unwrap_list_item_type(type_annotation=type_annotation)
    return type_annotation, type_is_list


def is_pydantic_model(t: type) -> bool:
    return issubclass(t, pydantic.BaseModel) or (
        hasattr(t, "__pydantic_model__")
        and issubclass(t.__pydantic_model__, pydantic.BaseModel)
    )
