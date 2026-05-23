from __future__ import annotations

import typing as t

from pydantic import BaseModel, TypeAdapter

from .bridge import Bridge


def generate_openapi(bridge: Bridge, *, title: str = "PyBridge API", version: str = "0.1.0") -> dict:
    paths: dict[str, dict] = {}
    components: dict[str, dict] = {}

    for path, proc in bridge.procedures.items():
        if proc.kind == "subscription":
            continue
        request_schema = _schema_for(proc.input_type, components) if proc.input_type else None
        response_schema = _schema_for(proc.output_type, components) if proc.output_type else {"type": "null"}
        op: dict = {
            "operationId": path.replace(".", "_"),
            "responses": {
                "200": {
                    "description": "OK",
                    "content": {"application/json": {"schema": response_schema}},
                },
                "400": {
                    "description": "Procedure error",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProcedureError"}}},
                },
            },
        }
        if request_schema is not None:
            op["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": request_schema}},
            }
        paths[f"/rpc/{path}"] = {"post": op}

    components["ProcedureError"] = {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "data": {},
                },
                "required": ["code", "message"],
            }
        },
        "required": ["error"],
    }

    return {
        "openapi": "3.0.3",
        "info": {"title": title, "version": version},
        "paths": paths,
        "components": {"schemas": components},
    }


def _schema_for(tp: t.Any, components: dict[str, dict]) -> dict:
    adapter = TypeAdapter(tp)
    schema = adapter.json_schema(ref_template="#/components/schemas/{model}")
    defs = schema.pop("$defs", None) or schema.pop("definitions", None)
    if defs:
        for name, sub in defs.items():
            components.setdefault(name, sub)
    return schema
