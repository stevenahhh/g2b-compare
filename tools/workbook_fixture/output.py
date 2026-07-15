"""Contained atomic publication for generated workbook fixtures."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from .models import FixtureError

if TYPE_CHECKING:
    from pydantic import BaseModel

_REPARSE_POINT_ATTRIBUTE: Final = 0x400


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int


def _absolute(path: Path) -> Path:
    return path.absolute()


def _path_chain(path: Path) -> tuple[Path, ...]:
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    chain = [current]
    for part in absolute.parts[1:]:
        current /= part
        chain.append(current)
    return tuple(chain)


def _is_redirect(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & _REPARSE_POINT_ATTRIBUTE)


def _directory_identity(path: Path) -> _FileIdentity:
    info = path.lstat()
    if _is_redirect(info):
        message = f"symbolic link or reparse point in output path: {path}"
        raise FixtureError(message)
    if not stat.S_ISDIR(info.st_mode):
        message = f"output path component is not a directory: {path}"
        raise FixtureError(message)
    return _FileIdentity(device=info.st_dev, inode=info.st_ino)


def _prepare_directory(path: Path) -> Path:
    absolute = _absolute(path)
    for component in _path_chain(absolute):
        try:
            _ = _directory_identity(component)
        except FileNotFoundError:
            with suppress(FileExistsError):
                component.mkdir()
            _ = _directory_identity(component)
    return absolute


def _validate_directory_chain(path: Path) -> None:
    for component in _path_chain(path):
        _ = _directory_identity(component)


def _target_identity(path: Path) -> _FileIdentity | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if _is_redirect(info):
        message = f"symbolic link or reparse point output target: {path}"
        raise FixtureError(message)
    if not stat.S_ISREG(info.st_mode):
        message = f"output target is not a regular file: {path}"
        raise FixtureError(message)
    if info.st_nlink != 1:
        message = f"hard link output target rejected: {path}"
        raise FixtureError(message)
    return _FileIdentity(device=info.st_dev, inode=info.st_ino)


def _render_json(value: BaseModel) -> bytes:
    text = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return f"{text}\n".encode()


def _contained_target(root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        message = f"absolute output path rejected: {relative_path}"
        raise FixtureError(message)
    target = _absolute(root / relative_path)
    if not target.is_relative_to(root):
        message = f"output path escapes root: {relative_path}"
        raise FixtureError(message)
    return target


def validate_output_paths(output_root: Path, relative_paths: tuple[Path, ...]) -> None:
    """Reject every unsafe output path before publishing the first file."""
    root = _prepare_directory(output_root)
    for relative_path in relative_paths:
        target = _contained_target(root, relative_path)
        _ = _prepare_directory(target.parent)
        _ = _target_identity(target)


def write_json_atomic(output_root: Path, relative_path: Path, value: BaseModel) -> None:
    """Publish JSON without following links or exposing a partial target."""
    root = _prepare_directory(output_root)
    target = _contained_target(root, relative_path)
    parent = _prepare_directory(target.parent)
    parent_identity = _directory_identity(parent)
    target_identity = _target_identity(target)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(_render_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        _validate_directory_chain(parent)
        if _directory_identity(parent) != parent_identity:
            message = f"output parent changed during publication: {parent}"
            raise FixtureError(message)
        if _target_identity(target) != target_identity:
            message = f"output target changed during publication: {target}"
            raise FixtureError(message)
        _ = temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
