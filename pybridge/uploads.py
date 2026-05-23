from __future__ import annotations

import typing as t
from dataclasses import dataclass

from pydantic_core import core_schema


@dataclass
class UploadFile:
    """A file received from a multipart/form-data request.

    Procedures that accept an ``UploadFile`` (or ``list[UploadFile]``) field on
    their input model are routed through the multipart parser. The TypeScript
    side renders this as ``File`` (or ``File[]``).
    """

    filename: str
    content_type: str
    data: bytes

    def __len__(self) -> int:
        return len(self.data)

    @classmethod
    def __get_pydantic_core_schema__(cls, _source, _handler):
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(lambda v: v.filename),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, _schema, _handler):
        return {"type": "string", "format": "binary"}

    @classmethod
    def _validate(cls, value):
        if isinstance(value, cls):
            return value
        raise TypeError(f"expected UploadFile, got {type(value).__name__}")


def model_has_upload(model: type) -> bool:
    from pydantic import BaseModel

    if not isinstance(model, type) or not issubclass(model, BaseModel):
        return False
    for field in model.model_fields.values():
        if _annotation_has_upload(field.annotation):
            return True
    return False


def _annotation_has_upload(tp: t.Any) -> bool:
    if tp is UploadFile:
        return True
    origin = t.get_origin(tp)
    if origin is not None:
        return any(_annotation_has_upload(a) for a in t.get_args(tp))
    return False
