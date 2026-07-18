"""Typed values accepted by the server-rendered template boundary."""

from collections.abc import Mapping, Sequence

from fastapi import Request

type ViewValue = (
    str
    | int
    | float
    | bool
    | None
    | Request
    | Sequence[ViewValue]
    | Mapping[str, ViewValue]
)
