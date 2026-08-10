#!/usr/bin/env python3
"""Packaged Windows Tauri desktop QA harness.

The harness attaches Playwright to the packaged WebView2 through its supported
Chrome DevTools Protocol switch. It never passes credentials to the process,
and it records unavailable planned commands instead of modifying the app.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, TextIO, cast, final
from uuid import uuid4

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)

INSTALLED_PARITY_SCENARIO: Final = "installed-parity"
INSTALLED_PARITY_CHILD_SCENARIOS: Final = ("full-parity", "adversarial")
INSTALLED_PARITY_CLEANUP_FLAGS: Final = (
    "directory_removed",
    "registry_removed",
    "process_cleanup",
    "ports_closed",
)
SCENARIOS: Final = (
    "startup-catalog",
    "full-parity",
    "adversarial",
    INSTALLED_PARITY_SCENARIO,
)
MIN_TIMEOUT_SECONDS: Final = 5
MAX_TIMEOUT_SECONDS: Final = 600
MIN_SECRET_LENGTH: Final = 6
CATALOG_PAGE_SIZE: Final = 30
PREFERRED_COMPANY: Final = "주식회사 코리아넷"
HARNESS_SOURCE: Final = Path(__file__).resolve()
UNINSTALL_REGISTRY_SUBKEY: Final = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\G2B Compare Desktop"
)
UNINSTALL_REGISTRY_PARENT: Final = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
)
INSTALLED_EXECUTABLE_NAME: Final = "g2b-compare-desktop.exe"
SHA256_HEX: Final = re.compile(r"^[0-9a-f]{64}$")
RUN_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SENSITIVE_KEY: Final = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|password|secret|token)",
    re.IGNORECASE,
)
BEARER_VALUE: Final = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+|bearer\s+)[^\s,;]+"
)
QUERY_SECRET: Final = re.compile(
    r"(?i)([?&](?:serviceKey|api[_-]?key|token|secret)=)[^&#\s]+"
)
UNKNOWN_COMMAND: Final = re.compile(
    r"unknown command|command .* not found|not registered|not allowed",
    re.IGNORECASE,
)
DATA_COUNT_KEYS: Final = (
    "company_count",
    "product_count",
    "relation_count",
    "option_row_count",
    "unique_option_count",
    "pending_api_target_count",
    "pending_site_product_count",
)
PLANNED_COMMANDS: Final = (
    "export_estimate_workbook",
    "copy_estimate_table",
    "load_desktop_view",
    "save_desktop_view",
    "get_reconciliation_status",
    "replay_pending_changes",
    "resolve_reconciliation_conflict",
)
QA_REPLAY_ESTIMATE_ID: Final = "00112233445566778899aabbccddeeff"
QA_REPLAY_LINE_ID: Final = "ffeeddccbbaa99887766554433221100"
QA_REPLAY_TEMPLATE_SHA256: Final = (
    "f344d2fcd12612170677eacc8b6ee4798ef730b8f5ea91b40ba8d7fcf0d694e4"
)
QA_REPLAY_TOTAL_WON: Final = 1000
LEGACY_DOCUMENT_COLUMN_COUNT: Final = 18
LEGACY_CLIPBOARD_COLUMN_COUNT: Final = 17
COMPARISON_SLOT_COUNT: Final = 3
RELATION_FIXTURE_PRODUCT_ID: Final = "25454885"
MAX_TCP_PORT: Final = 65535


class ReceiptStatus(StrEnum):
    """Outcome for one independently inspectable QA check."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CliOptions:
    """Validated command-line options."""

    scenario: str
    exe: Path | None
    installer: Path | None
    evidence_dir: Path
    timeout_seconds: int
    cleanup_only: bool
    keep_qa_data: bool
    qa_harness_sha256: str | None
    expected_exe_sha256: str | None
    expected_installer_sha256: str | None
    installed_child: bool
    run_id: str | None


@dataclass(frozen=True)
class InvokeResult:
    """Result returned by the in-WebView Tauri command bridge."""

    ok: bool
    value: object | None
    error: str | None


class FeatureUnavailableError(RuntimeError):
    """The packaged app does not expose a planned QA seam yet."""


def _sha256_option(value: str) -> str:
    """Validate a lower-case SHA-256 digest passed across a QA process boundary."""
    if not SHA256_HEX.fullmatch(value):
        msg = "SHA-256 values must be 64 lower-case hexadecimal characters"
        raise argparse.ArgumentTypeError(msg)
    return value


def _run_id_option(value: str) -> str:
    """Validate an evidence-directory-safe, deterministic run identifier."""
    if not RUN_ID.fullmatch(value):
        msg = "run ID must be 1..128 letters, digits, dots, underscores, or hyphens"
        raise argparse.ArgumentTypeError(msg)
    return value


@dataclass(frozen=True)
class ReceiptContext:
    """The source-bound identity and redaction controls for one child receipt."""

    scenario: str
    run_id: str
    secrets: Sequence[str] = ()
    clock: Callable[[], str] | None = None
    expected_qa_harness_sha256: str | None = None


@final
class ReceiptStore:
    """Append-only, secret-safe structured receipts for one harness run."""

    def __init__(self, evidence_dir: Path, context: ReceiptContext) -> None:
        """Create a fresh run directory and configure recursive redaction."""
        actual_harness_sha256 = sha256_file(HARNESS_SOURCE)
        if (
            context.expected_qa_harness_sha256 is not None
            and context.expected_qa_harness_sha256 != actual_harness_sha256
        ):
            msg = "the executing QA harness source does not match its parent hash"
            raise RuntimeError(msg)
        self.scenario = context.scenario
        self.run_id = context.run_id
        self.qa_harness_sha256 = actual_harness_sha256
        self.run_dir = evidence_dir.resolve() / context.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._events_path = self.run_dir / "events.jsonl"
        self._summary_path = self.run_dir / "receipt.json"
        self._events: list[dict[str, object]] = []
        self._clock = context.clock or utc_now
        self._secrets = tuple(
            sorted(
                {value for value in context.secrets if len(value) >= MIN_SECRET_LENGTH},
                key=len,
                reverse=True,
            )
        )

    def sanitize_text(self, value: str) -> str:
        """Remove known and recognizable credential values from text."""
        safe = value
        for secret in self._secrets:
            safe = safe.replace(secret, "[REDACTED]")
        safe = BEARER_VALUE.sub(lambda match: f"{match.group(1)}[REDACTED]", safe)
        return QUERY_SECRET.sub(lambda match: f"{match.group(1)}[REDACTED]", safe)

    def _sanitize(self, value: object, *, key: str = "") -> object:
        if key and SENSITIVE_KEY.search(key):
            return "[REDACTED]"
        if isinstance(value, str):
            return self.sanitize_text(value)
        if isinstance(value, Mapping):
            sanitized: dict[str, object] = {}
            mapping = cast("Mapping[object, object]", value)
            for nested_key, nested_value in mapping.items():
                name = str(nested_key)
                sanitized[name] = self._sanitize(nested_value, key=name)
            return sanitized
        if isinstance(value, (list, tuple)):
            sequence = cast("Sequence[object]", value)
            return [self._sanitize(item) for item in sequence]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self.sanitize_text(str(value))

    def record(
        self,
        check: str,
        status: ReceiptStatus,
        details: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Append one numbered event and flush it to disk immediately."""
        event: dict[str, object] = {
            "sequence": len(self._events) + 1,
            "timestamp": self._clock(),
            "scenario": self.scenario,
            "check": check,
            "status": status.value,
            "details": self._sanitize(dict(details or {})),
        }
        self._events.append(event)
        with self._events_path.open("a", encoding="utf-8", newline="\n") as stream:
            _ = stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            _ = stream.write("\n")
            stream.flush()
            _ = os.fsync(stream.fileno())
        return event

    def artifact_path(self, category: str, name: str) -> Path:
        """Return a contained path for a run artifact and create its directory."""
        if not category or Path(category).is_absolute() or ".." in Path(category).parts:
            msg = "artifact category must be a relative contained path"
            raise ValueError(msg)
        safe_name = Path(name).name
        if safe_name != name or not safe_name:
            msg = "artifact name must be a single non-empty filename"
            raise ValueError(msg)
        directory = self.run_dir / category
        directory.mkdir(parents=True, exist_ok=True)
        return directory / safe_name

    def relative_artifact(self, path: Path) -> str:
        """Represent an artifact relative to this run, rejecting path escape."""
        try:
            return path.resolve().relative_to(self.run_dir).as_posix()
        except ValueError as error:
            msg = "artifact is outside the run evidence directory"
            raise ValueError(msg) from error

    def finish(self) -> dict[str, object]:
        """Write and return the final deterministic summary receipt."""
        counts = {
            status.value: sum(event["status"] == status.value for event in self._events)
            for status in (
                ReceiptStatus.FAILED,
                ReceiptStatus.PASSED,
                ReceiptStatus.UNAVAILABLE,
            )
        }
        outcome = (
            ReceiptStatus.FAILED.value
            if counts[ReceiptStatus.FAILED.value]
            else ReceiptStatus.UNAVAILABLE.value
            if counts[ReceiptStatus.UNAVAILABLE.value]
            else ReceiptStatus.PASSED.value
        )
        summary: dict[str, object] = {
            "schema_version": 1,
            "run_id": self.run_id,
            "scenario": self.scenario,
            "qa_harness_sha256": self.qa_harness_sha256,
            "finished_at": self._clock(),
            "outcome": outcome,
            "counts": counts,
            "events": self._events,
        }
        temporary = self._summary_path.with_suffix(".json.tmp")
        _ = temporary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _ = temporary.replace(self._summary_path)
        return summary


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bounded_timeout(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        msg = "timeout must be an integer number of seconds"
        raise argparse.ArgumentTypeError(msg) from error
    if not MIN_TIMEOUT_SECONDS <= parsed <= MAX_TIMEOUT_SECONDS:
        msg = (
            f"timeout must be between {MIN_TIMEOUT_SECONDS} and "
            f"{MAX_TIMEOUT_SECONDS} seconds"
        )
        raise argparse.ArgumentTypeError(msg)
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> CliOptions:
    """Parse strict CLI arguments and validate filesystem boundaries."""
    parser = argparse.ArgumentParser(
        description="Drive and receipt a packaged Windows Tauri desktop build.",
        allow_abbrev=False,
    )
    _ = parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    _ = parser.add_argument("--exe", type=Path)
    _ = parser.add_argument("--installer", type=Path)
    _ = parser.add_argument("--evidence-dir", required=True, type=Path)
    _ = parser.add_argument("--run-id", type=_run_id_option)
    _ = parser.add_argument(
        "--timeout-seconds",
        type=_bounded_timeout,
        default=30,
        metavar=f"{MIN_TIMEOUT_SECONDS}..{MAX_TIMEOUT_SECONDS}",
    )
    _ = parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="remove prior qa-state directories under the evidence directory",
    )
    _ = parser.add_argument(
        "--keep-qa-data",
        action="store_true",
        help="retain isolated QA AppData after the run for diagnosis",
    )
    _ = parser.add_argument(
        "--installed-child",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    _ = parser.add_argument(
        "--qa-harness-sha256",
        type=_sha256_option,
        help=argparse.SUPPRESS,
    )
    _ = parser.add_argument(
        "--expected-exe-sha256",
        type=_sha256_option,
        help=argparse.SUPPRESS,
    )
    _ = parser.add_argument(
        "--expected-installer-sha256",
        type=_sha256_option,
        help=argparse.SUPPRESS,
    )
    namespace = parser.parse_args(argv)
    scenario = cast("str", namespace.scenario)
    executable = cast("Path | None", namespace.exe)
    installer = cast("Path | None", namespace.installer)
    evidence_dir = cast("Path", namespace.evidence_dir).resolve()
    cleanup_only = cast("bool", namespace.cleanup_only)
    keep_qa_data = cast("bool", namespace.keep_qa_data)
    timeout_seconds = cast("int", namespace.timeout_seconds)
    qa_harness_sha256 = cast("str | None", namespace.qa_harness_sha256)
    expected_exe_sha256 = cast("str | None", namespace.expected_exe_sha256)
    expected_installer_sha256 = cast("str | None", namespace.expected_installer_sha256)
    installed_child = cast("bool", namespace.installed_child)
    run_id = cast("str | None", namespace.run_id)

    options = CliOptions(
        scenario=scenario,
        exe=_resolve_executable_option(parser, executable, "--exe"),
        installer=_resolve_executable_option(parser, installer, "--installer"),
        evidence_dir=evidence_dir,
        timeout_seconds=timeout_seconds,
        cleanup_only=cleanup_only,
        keep_qa_data=keep_qa_data,
        qa_harness_sha256=qa_harness_sha256,
        expected_exe_sha256=expected_exe_sha256,
        expected_installer_sha256=expected_installer_sha256,
        installed_child=installed_child,
        run_id=run_id,
    )
    _validate_common_cli_options(parser, options)
    _validate_scenario_cli_options(parser, options)
    return options


def _resolve_executable_option(
    parser: argparse.ArgumentParser, path: Path | None, option: str
) -> Path | None:
    """Resolve and validate one command-line executable boundary."""
    if path is None:
        return None
    resolved = path.resolve()
    if not resolved.is_file() or resolved.suffix.lower() != ".exe":
        parser.error(f"{option} must name an existing .exe file")
    return resolved


def _validate_common_cli_options(
    parser: argparse.ArgumentParser, options: CliOptions
) -> None:
    """Validate filesystem and cleanup rules shared by every scenario mode."""
    is_installed_parity = options.scenario == INSTALLED_PARITY_SCENARIO
    if options.exe is None and not options.cleanup_only and not is_installed_parity:
        parser.error("--exe is required unless --cleanup-only is used")
    if options.evidence_dir.exists() and not options.evidence_dir.is_dir():
        parser.error("--evidence-dir must be a directory path")
    if options.cleanup_only and options.keep_qa_data:
        parser.error("--cleanup-only and --keep-qa-data cannot be combined")
    has_internal_option = any(
        value is not None
        for value in (
            options.qa_harness_sha256,
            options.expected_exe_sha256,
            options.expected_installer_sha256,
        )
    )
    if options.cleanup_only and (options.installed_child or has_internal_option):
        parser.error(
            "internal installed-parity options cannot be used with --cleanup-only"
        )


def _validate_scenario_cli_options(
    parser: argparse.ArgumentParser, options: CliOptions
) -> None:
    """Validate mutually exclusive top-level and internal installed-parity modes."""
    if options.scenario == INSTALLED_PARITY_SCENARIO:
        _validate_installed_parity_options(parser, options)
        return
    if options.installer is not None and not options.installed_child:
        message = (
            "--installer is reserved for --scenario installed-parity; "
            "loose executable scenarios must not claim installer provenance"
        )
        parser.error(message)
    _validate_installed_child_options(parser, options)


def _validate_installed_parity_options(
    parser: argparse.ArgumentParser, options: CliOptions
) -> None:
    """Reject inputs that could bypass the top-level installed provenance chain."""
    if options.cleanup_only:
        parser.error("--scenario installed-parity cannot be used with --cleanup-only")
    if options.exe is not None:
        parser.error("--scenario installed-parity resolves --exe from the installer")
    if options.keep_qa_data:
        parser.error("--scenario installed-parity always removes child QA state")
    if options.installer is None:
        parser.error("--scenario installed-parity requires --installer")
    if options.installed_child:
        parser.error("--installed-child is internal and cannot use installed-parity")
    if (
        options.expected_exe_sha256 is not None
        or options.expected_installer_sha256 is not None
        or options.qa_harness_sha256 is not None
    ):
        parser.error("expected artifact hashes are reserved for installed child runs")


def _validate_installed_child_options(
    parser: argparse.ArgumentParser, options: CliOptions
) -> None:
    """Require complete parent provenance for an internal installed child run."""
    expected_hashes = (
        options.qa_harness_sha256,
        options.expected_exe_sha256,
        options.expected_installer_sha256,
    )
    if options.installed_child:
        if options.exe is None or options.installer is None:
            parser.error("--installed-child requires both --exe and --installer")
        if any(value is None for value in expected_hashes):
            parser.error(
                "--installed-child requires all expected source and artifact hashes"
            )
    elif any(value is not None for value in expected_hashes):
        parser.error(
            "expected source and artifact hashes are reserved for installed child runs"
        )


def environment_secrets() -> tuple[str, ...]:
    """Collect credential-like environment values for output redaction only."""
    values: list[str] = []
    for name, value in os.environ.items():
        if SENSITIVE_KEY.search(name) and value:
            values.append(value)
    return tuple(values)


def qa_replay_database(state_root: Path) -> Path:
    """Return the existing replay database owned by one isolated QA run."""
    database = state_root / "app-data" / "offline-replay.sqlite3"
    if not database.is_file():
        msg = "isolated QA replay database was not created before injection"
        raise FileNotFoundError(msg)
    return database


def inject_qa_replay_mutation(state_root: Path) -> int:
    """Insert one valid create mutation into the stopped run's replay database."""
    database = qa_replay_database(state_root)
    mutation = {
        "operation": "create_estimate",
        "request": {
            "id": QA_REPLAY_ESTIMATE_ID,
            "title": "QA offline replay estimate",
            "template_sha256": QA_REPLAY_TEMPLATE_SHA256,
            "lines": [
                {
                    "id": QA_REPLAY_LINE_ID,
                    "line_kind": "main",
                    "product_id": "24492324",
                    "parent_product_id": None,
                    "relation_id": None,
                    "offer_operation": None,
                    "offer_key": None,
                    "item_name_snapshot": "QA replay item",
                    "spec_snapshot": "QA replay specification",
                    "company_snapshot": "QA replay company",
                    "unit_snapshot": "EA",
                    "unit_price_won_snapshot": QA_REPLAY_TOTAL_WON,
                    "quantity": "1",
                }
            ],
            "comparisons": [],
        },
    }
    payload = json.dumps(
        mutation, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    with sqlite3.connect(database) as connection:
        queued = require_int(
            sqlite_scalar(connection, "SELECT COUNT(*) FROM offline_replay_mutations"),
            "queued mutation count",
        )
        if queued != 0:
            msg = f"isolated QA replay queue was not empty before injection: {queued}"
            raise AssertionError(msg)
        cursor = connection.execute(
            "INSERT INTO offline_replay_mutations (entity_id, payload) VALUES (?, ?)",
            (QA_REPLAY_ESTIMATE_ID, payload),
        )
        sequence = cursor.lastrowid
        if not isinstance(sequence, int) or sequence < 1:
            msg = "QA replay mutation did not receive a positive durable sequence"
            raise RuntimeError(msg)
    return sequence


def qa_replay_queue_count(state_root: Path) -> int:
    """Read the durable queue count from the stopped run's isolated replay database."""
    database = qa_replay_database(state_root)
    uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        return require_int(
            sqlite_scalar(connection, "SELECT COUNT(*) FROM offline_replay_mutations"),
            "queued mutation count",
        )


class _CtypesFunction(Protocol):
    """Typed surface shared by the three configured Win32 functions."""

    argtypes: list[object]
    restype: object

    def __call__(self, *arguments: object) -> object:
        """Call the configured Win32 function."""
        ...


@final
class _JobBasicLimits(ctypes.Structure):
    """Win32 `JOBOBJECT_BASIC_LIMIT_INFORMATION` layout."""

    _fields_ = (
        ("per_process_user_time", ctypes.c_int64),
        ("per_job_user_time", ctypes.c_int64),
        ("limit_flags", ctypes.c_uint32),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_uint32),
        ("scheduling_class", ctypes.c_uint32),
    )


@final
class _IoCounters(ctypes.Structure):
    """Win32 `IO_COUNTERS` layout."""

    _fields_ = tuple((f"counter_{index}", ctypes.c_uint64) for index in range(6))


@final
class _JobExtendedLimits(ctypes.Structure):
    """Win32 `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` layout."""

    _fields_ = (
        ("basic_limits", _JobBasicLimits),
        ("io_counters", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    )


def windows_function(
    library: object, name: str, argtypes: list[object], restype: object
) -> _CtypesFunction:
    """Configure and return one typed Win32 entry point."""
    function = cast("_CtypesFunction", getattr(library, name))
    function.argtypes = argtypes
    function.restype = restype
    return function


def read_windows_clipboard_text() -> str:
    """Read the exact native Unicode clipboard projection once."""
    if sys.platform != "win32":
        msg = "native clipboard verification requires Windows"
        raise FeatureUnavailableError(msg)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_clipboard = windows_function(
        user32,
        "OpenClipboard",
        [ctypes.c_void_p],
        ctypes.c_int,
    )
    close_clipboard = windows_function(user32, "CloseClipboard", [], ctypes.c_int)
    get_clipboard_data = windows_function(
        user32,
        "GetClipboardData",
        [ctypes.c_uint32],
        ctypes.c_void_p,
    )
    global_lock = windows_function(
        kernel32,
        "GlobalLock",
        [ctypes.c_void_p],
        ctypes.c_void_p,
    )
    global_unlock = windows_function(
        kernel32,
        "GlobalUnlock",
        [ctypes.c_void_p],
        ctypes.c_int,
    )
    if not open_clipboard(None):
        error_code = ctypes.get_last_error()
        raise OSError(error_code, "OpenClipboard failed")
    try:
        handle = get_clipboard_data(13)
        if not handle:
            return ""
        pointer = global_lock(handle)
        if not pointer:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "GlobalLock clipboard failed")
        try:
            return ctypes.wstring_at(cast("int", pointer))
        finally:
            _ = global_unlock(handle)
    finally:
        _ = close_clipboard()


def require_windows_success(result: object, operation: str) -> None:
    """Raise the exact last-error failure for one Win32 boolean operation."""
    if not result:
        error_code = ctypes.get_last_error()
        raise OSError(error_code, f"{operation} failed")


@final
class WindowsProcessTree:
    """A job object that owns and reaps only this QA run's child tree."""

    _EXTENDED_LIMITS: Final = 9
    _PROCESS_ID_LIST: Final = 3
    _KILL_ON_CLOSE: Final = 0x00002000
    _SET_QUOTA: Final = 0x0100
    _TERMINATE: Final = 0x0001
    _SYNCHRONIZE: Final = 0x00100000
    _MAX_PROCESSES: Final = 256
    _INVALID_PARAMETER: Final = 87
    _WAIT_OBJECT_0: Final = 0
    _WAIT_TIMEOUT: Final = 0x00000102

    def __init__(self, process_id: int) -> None:
        """Create a kill-on-close job and immediately assign the QA root process."""
        if sys.platform != "win32":
            msg = "packaged desktop automation requires Windows"
            raise FeatureUnavailableError(msg)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_job = windows_function(
            self._kernel32,
            "CreateJobObjectW",
            [ctypes.c_void_p, ctypes.c_wchar_p],
            ctypes.c_void_p,
        )
        self._handle = cast("int | None", create_job(None, None))
        if not self._handle:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "CreateJobObjectW failed for packaged QA run")
        try:
            limits = _JobExtendedLimits()
            ctypes.c_uint32.from_buffer(limits, 16).value = self._KILL_ON_CLOSE
            set_information = windows_function(
                self._kernel32,
                "SetInformationJobObject",
                [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32],
                ctypes.c_int,
            )
            require_windows_success(
                set_information(
                    self._handle,
                    self._EXTENDED_LIMITS,
                    ctypes.byref(limits),
                    ctypes.sizeof(limits),
                ),
                "SetInformationJobObject",
            )
            self._assign(process_id)
        except Exception:
            self.close()
            raise

    def _assign(self, process_id: int) -> None:
        open_process = windows_function(
            self._kernel32,
            "OpenProcess",
            [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32],
            ctypes.c_void_p,
        )
        process = cast(
            "int | None",
            open_process(
                self._SET_QUOTA | self._TERMINATE | self._SYNCHRONIZE,
                0,
                process_id,
            ),
        )
        if not process:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "OpenProcess failed for packaged QA process")
        try:
            assign = windows_function(
                self._kernel32,
                "AssignProcessToJobObject",
                [ctypes.c_void_p, ctypes.c_void_p],
                ctypes.c_int,
            )
            if not assign(self.handle, process):
                error_code = ctypes.get_last_error()
                raise OSError(error_code, "AssignProcessToJobObject failed")
        finally:
            self._close_handle(process)

    @property
    def handle(self) -> int:
        """Return the open job handle or fail before touching another process."""
        if self._handle is None:
            msg = "QA process job is already closed"
            raise RuntimeError(msg)
        return self._handle

    def _close_handle(self, handle: int) -> None:
        close_handle = windows_function(
            self._kernel32,
            "CloseHandle",
            [ctypes.c_void_p],
            ctypes.c_int,
        )
        if not close_handle(handle):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "CloseHandle failed for packaged QA process")

    def _member_process_handles(self) -> list[int]:
        pointer_size = ctypes.sizeof(ctypes.c_size_t)
        header_size = 2 * ctypes.sizeof(ctypes.c_uint32)
        buffer_size = header_size + self._MAX_PROCESSES * pointer_size
        buffer = ctypes.create_string_buffer(buffer_size)
        returned = ctypes.c_uint32()
        query = windows_function(
            self._kernel32,
            "QueryInformationJobObject",
            [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
            ],
            ctypes.c_int,
        )
        if not query(
            self.handle,
            self._PROCESS_ID_LIST,
            ctypes.byref(buffer),
            buffer_size,
            ctypes.byref(returned),
        ):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "QueryInformationJobObject failed")
        count = ctypes.c_uint32.from_buffer_copy(
            buffer.raw, ctypes.sizeof(ctypes.c_uint32)
        ).value
        if count > self._MAX_PROCESSES:
            msg = "QA process tree exceeded the tracked process-handle limit"
            raise RuntimeError(msg)
        open_process = windows_function(
            self._kernel32,
            "OpenProcess",
            [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32],
            ctypes.c_void_p,
        )
        handles: list[int] = []
        for index in range(count):
            process_id = ctypes.c_size_t.from_buffer_copy(
                buffer.raw, header_size + index * pointer_size
            ).value
            handle = cast("int | None", open_process(self._SYNCHRONIZE, 0, process_id))
            if handle:
                handles.append(handle)
                continue
            error_code = ctypes.get_last_error()
            if error_code != self._INVALID_PARAMETER:
                raise OSError(error_code, "OpenProcess failed for a QA child process")
        return handles

    def terminate_and_wait(self, timeout_ms: int) -> None:
        """Terminate this job only and await every captured process handle."""
        handles = self._member_process_handles()
        try:
            terminate = windows_function(
                self._kernel32,
                "TerminateJobObject",
                [ctypes.c_void_p, ctypes.c_uint32],
                ctypes.c_int,
            )
            if not terminate(self.handle, 1):
                error_code = ctypes.get_last_error()
                raise OSError(error_code, "TerminateJobObject failed")
            wait = windows_function(
                self._kernel32,
                "WaitForSingleObject",
                [ctypes.c_void_p, ctypes.c_uint32],
                ctypes.c_uint32,
            )
            for handle in handles:
                result = cast("int", wait(handle, timeout_ms))
                if result == self._WAIT_OBJECT_0:
                    continue
                if result == self._WAIT_TIMEOUT:
                    msg = "a run-owned WebView2 process did not exit before cleanup"
                    raise TimeoutError(msg)
                error_code = ctypes.get_last_error()
                raise OSError(error_code, "WaitForSingleObject failed for QA process")
        finally:
            for handle in handles:
                self._close_handle(handle)

    def close(self) -> None:
        """Close the job after its process handles have been awaited."""
        handle = self._handle
        self._handle = None
        if handle is not None:
            self._close_handle(handle)


class _DirectoryChangeWatcher(Protocol):
    """Event source for a watched WebView2 user-data directory."""

    def wait_for_change(self, timeout_ms: int) -> bool:
        """Wait for one filesystem change, returning false on timeout."""
        ...

    def close(self) -> None:
        """Release every Win32 handle owned by the watcher."""
        ...


@final
class _WindowsDevToolsChangeWatcher:
    """Wait for WebView2 profile changes and fail promptly if its root exits."""

    _FILE_NOTIFY_CHANGE_FILE_NAME: Final = 0x00000001
    _FILE_NOTIFY_CHANGE_LAST_WRITE: Final = 0x00000010
    _SYNCHRONIZE: Final = 0x00100000
    _WAIT_OBJECT_0: Final = 0
    _WAIT_TIMEOUT: Final = 0x00000102
    _WAIT_FAILED: Final = 0xFFFFFFFF

    def __init__(self, user_data_directory: Path) -> None:
        """Arm a directory notification before the packaged executable launches."""
        if sys.platform != "win32":
            msg = "packaged desktop automation requires Windows"
            raise FeatureUnavailableError(msg)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        find_first_change = windows_function(
            self._kernel32,
            "FindFirstChangeNotificationW",
            [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32],
            ctypes.c_void_p,
        )
        handle = cast(
            "int | None",
            find_first_change(
                str(user_data_directory),
                1,
                self._FILE_NOTIFY_CHANGE_FILE_NAME
                | self._FILE_NOTIFY_CHANGE_LAST_WRITE,
            ),
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle is None or handle == invalid_handle:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "FindFirstChangeNotificationW failed")
        self._change_handle: int | None = handle
        self._process_handle: int | None = None

    def watch_process(self, process_id: int) -> None:
        """Include the root process exit in subsequent notification waits."""
        if self._process_handle is not None:
            msg = "the packaged process is already being watched"
            raise RuntimeError(msg)
        open_process = windows_function(
            self._kernel32,
            "OpenProcess",
            [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32],
            ctypes.c_void_p,
        )
        handle = cast("int | None", open_process(self._SYNCHRONIZE, 0, process_id))
        if not handle:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "OpenProcess failed for packaged executable")
        self._process_handle = handle

    def wait_for_change(self, timeout_ms: int) -> bool:
        """Block on one profile change or root-process exit without polling."""
        change_handle = self._change_handle
        process_handle = self._process_handle
        if change_handle is None or process_handle is None:
            msg = "WebView2 readiness watcher is not fully configured"
            raise RuntimeError(msg)
        handles = (ctypes.c_void_p * 2)(process_handle, change_handle)
        wait = windows_function(
            self._kernel32,
            "WaitForMultipleObjects",
            [
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_int,
                ctypes.c_uint32,
            ],
            ctypes.c_uint32,
        )
        result = cast("int", wait(2, handles, 0, timeout_ms))
        if result == self._WAIT_OBJECT_0:
            msg = "packaged executable exited before WebView2 CDP became ready"
            raise RuntimeError(msg)
        if result == self._WAIT_OBJECT_0 + 1:
            find_next_change = windows_function(
                self._kernel32,
                "FindNextChangeNotification",
                [ctypes.c_void_p],
                ctypes.c_int,
            )
            require_windows_success(
                find_next_change(change_handle), "FindNextChangeNotification"
            )
            return True
        if result == self._WAIT_TIMEOUT:
            return False
        if result == self._WAIT_FAILED:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "WaitForMultipleObjects failed")
        msg = f"WaitForMultipleObjects returned unexpected result {result}"
        raise RuntimeError(msg)

    def _close_handle(self, handle: int) -> None:
        close_handle = windows_function(
            self._kernel32,
            "CloseHandle",
            [ctypes.c_void_p],
            ctypes.c_int,
        )
        require_windows_success(close_handle(handle), "CloseHandle")

    def close(self) -> None:
        """Close the process and change-notification handles once."""
        process_handle = self._process_handle
        self._process_handle = None
        if process_handle is not None:
            self._close_handle(process_handle)
        change_handle = self._change_handle
        self._change_handle = None
        if change_handle is not None:
            self._close_handle(change_handle)


def _devtools_active_port(marker: Path) -> int | None:
    """Read a complete Chromium DevTools port marker after a directory event."""
    try:
        contents = marker.read_text(encoding="ascii")
    except (FileNotFoundError, PermissionError):
        return None
    lines = contents.splitlines()
    if not lines:
        return None
    try:
        port = int(lines[0])
    except ValueError as error:
        msg = "WebView2 wrote an invalid DevToolsActivePort marker"
        raise RuntimeError(msg) from error
    if not 1 <= port <= MAX_TCP_PORT:
        msg = "WebView2 wrote an out-of-range DevTools port"
        raise RuntimeError(msg)
    return port


def wait_for_devtools_active_port(
    user_data_directory: Path,
    changes: _DirectoryChangeWatcher,
    timeout_ms: int,
    *,
    expected_port: int | None = None,
    clock_ms: Callable[[], int] | None = None,
) -> int:
    """Await evented DevTools readiness and return its published loopback port."""
    marker = user_data_directory / "EBWebView" / "DevToolsActivePort"
    now = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)
    deadline = now() + timeout_ms
    try:
        while True:
            if expected_port is not None and marker.is_file():
                return expected_port
            port = _devtools_active_port(marker)
            if port is not None:
                return port
            remaining_ms = deadline - now()
            if remaining_ms <= 0 or not changes.wait_for_change(remaining_ms):
                msg = (
                    "WebView2 did not create DevToolsActivePort before "
                    "the startup deadline"
                )
                raise TimeoutError(msg)
    finally:
        changes.close()


@final
class DesktopSession:
    """One packaged process plus a Playwright CDP attachment."""

    def __init__(
        self,
        executable: Path,
        state_root: Path,
        timeout_seconds: int,
        receipts: ReceiptStore,
    ) -> None:
        """Configure one process session without launching it."""
        self.executable = executable
        self.state_root = state_root
        self.timeout_seconds = timeout_seconds
        self.receipts = receipts
        self.process: subprocess.Popen[bytes] | None = None
        self._process_tree: WindowsProcessTree | None = None
        self.page: Page | None = None
        self.context: BrowserContext | None = None
        self.browser: Browser | None = None
        self.playwright: Playwright | None = None
        self._stdout: TextIO | None = None
        self._stderr: TextIO | None = None
        self.devtools_port: int | None = None

    def start(self) -> Page:
        """Launch with isolated AppData, await CDP readiness, and attach once."""
        port = self._launch_process()
        self.devtools_port = port
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}",
                timeout=self.timeout_seconds * 1000,
            )
        except PlaywrightError as error:
            msg = (
                "WebView2 CDP inspection is unavailable; the executable must honor "
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
            )
            raise FeatureUnavailableError(msg) from error
        contexts = self.browser.contexts
        pages = [page for context in contexts for page in context.pages]
        if not pages:
            msg = "WebView2 exposed no inspectable page"
            raise FeatureUnavailableError(msg)
        preferred = [
            page
            for page in pages
            if "tauri" in page.url.lower() or page.url.startswith("http://localhost")
        ]
        self.page = preferred[0] if preferred else pages[-1]
        try:
            self.page.wait_for_url(
                re.compile(r"^(?:tauri|https?://)"),
                wait_until="commit",
                timeout=self.timeout_seconds * 1000,
            )
        except PlaywrightError as error:
            development_target = self.page.url.startswith("http://127.0.0.1:1420")
            if development_target or "ERR_CONNECTION_REFUSED" in str(error):
                msg = (
                    "the executable targets an unavailable development URL; "
                    "a packaged build is required"
                )
                raise FeatureUnavailableError(msg) from error
            raise
        if self.page.url.startswith("http://127.0.0.1:1420"):
            msg = (
                "the executable targets the Tauri development server; "
                "a packaged build is required"
            )
            raise FeatureUnavailableError(msg)
        self.context = self.page.context
        self.page.set_default_timeout(self.timeout_seconds * 1000)
        self.page.set_default_navigation_timeout(self.timeout_seconds * 1000)
        try:
            self.page.get_by_role("heading", name="나라장터 물품 비교").wait_for()
        except PlaywrightError as error:
            if self.page.url.startswith("http://127.0.0.1:1420"):
                msg = (
                    "the executable targets the Tauri development server; "
                    "a packaged build is required"
                )
                raise FeatureUnavailableError(msg) from error
            raise
        return self.page

    def _launch_process(self) -> int:
        self.state_root.mkdir(parents=True, exist_ok=True)
        roaming = self.state_root / "roaming"
        local = self.state_root / "local"
        webview2 = self.state_root / "webview2"
        for directory in (roaming, local, webview2):
            directory.mkdir(parents=True, exist_ok=True)
        devtools_active_port = webview2 / "EBWebView" / "DevToolsActivePort"
        if devtools_active_port.exists():
            devtools_active_port.unlink()
        watcher = _WindowsDevToolsChangeWatcher(webview2)
        self._stdout = (self.state_root / "process.stdout.log").open(
            "w", encoding="utf-8"
        )
        self._stderr = (self.state_root / "process.stderr.log").open(
            "w", encoding="utf-8"
        )
        environment = os.environ.copy()
        _ = environment.pop("G2B_SERVICE_KEY", None)
        environment.update(
            {
                "APPDATA": str(roaming),
                "LOCALAPPDATA": str(local),
                "G2B_COMPARE_APP_DATA_DIR": str(self.state_root / "app-data"),
                "WEBVIEW2_USER_DATA_FOLDER": str(webview2),
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": (
                    "--remote-debugging-port=0 --remote-allow-origins=*"
                ),
            }
        )
        try:
            self.process = subprocess.Popen(  # noqa: S603
                [str(self.executable)],
                cwd=self.executable.parent,
                env=environment,
                stdout=self._stdout,
                stderr=self._stderr,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self._process_tree = WindowsProcessTree(self.process.pid)
            watcher.watch_process(self.process.pid)
        except Exception:
            try:
                watcher.close()
            finally:
                _ = self._terminate_process()
            raise
        try:
            port = wait_for_devtools_active_port(
                webview2,
                watcher,
                self.timeout_seconds * 1000,
            )
        except Exception:
            _ = self._terminate_process()
            raise
        if self.process.poll() is not None:
            exit_code = self.process.returncode
            _ = self._terminate_process()
            msg = f"packaged executable exited with code {exit_code}"
            raise RuntimeError(msg)
        return port

    def stop(self) -> dict[str, object]:
        """Disconnect automation, terminate the process, and collect safe logs."""
        errors: list[str] = []
        port = self.devtools_port
        self._disconnect_playwright(errors)
        try:
            exit_code = self._terminate_process()
        finally:
            self._close_process_streams()
        port_closed = port is None or not loopback_port_is_open(port)
        if not port_closed:
            errors.append(f"run-owned DevTools port remained bound after stop: {port}")
        self.devtools_port = None
        return {
            "exit_code": exit_code,
            "errors": errors,
            "logs": self._safe_logs(),
            "devtools_port": port,
            "devtools_port_closed": port_closed,
        }

    def _disconnect_playwright(self, errors: list[str]) -> None:
        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception as error:  # noqa: BLE001  # pragma: no cover
                # Teardown must continue across third-party transport failures.
                errors.append(self.receipts.sanitize_text(str(error)))
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def _terminate_process(self) -> int | None:
        process = self.process
        process_tree = self._process_tree
        try:
            if process is not None and process.poll() is None:
                if process_tree is not None:
                    process_tree.terminate_and_wait(self.timeout_seconds * 1000)
                else:
                    process.terminate()
                try:
                    _ = process.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    _ = process.wait(timeout=self.timeout_seconds)
            return process.returncode if process is not None else None
        finally:
            if process_tree is not None:
                process_tree.close()
            self._process_tree = None
            self.process = None

    def _close_process_streams(self) -> None:
        for stream in (self._stdout, self._stderr):
            if stream is not None:
                stream.flush()
                stream.close()
        self._stdout = None
        self._stderr = None

    def _safe_logs(self) -> dict[str, object]:
        logs: dict[str, object] = {}
        for name in ("process.stdout.log", "process.stderr.log"):
            path = self.state_root / name
            if path.is_file():
                text = self.receipts.sanitize_text(path.read_text(encoding="utf-8"))
                safe_path = self.receipts.artifact_path("logs", name)
                _ = safe_path.write_text(text, encoding="utf-8")
                logs[name] = {
                    "artifact": self.receipts.relative_artifact(safe_path),
                    "bytes": len(text.encode()),
                }
        return logs


@final
class QaRunner:
    """Scenario orchestration over a packaged desktop session."""

    def __init__(self, options: CliOptions, receipts: ReceiptStore) -> None:
        """Bind validated CLI options to one isolated run state root."""
        if options.exe is None:
            msg = "an executable is required for scenario execution"
            raise ValueError(msg)
        self.options = options
        self.receipts = receipts
        self.state_root = receipts.run_dir / "qa-state"
        self.session = DesktopSession(
            options.exe,
            self.state_root,
            options.timeout_seconds,
            receipts,
        )
        self.page: Page | None = None
        self._first_product: dict[str, object] | None = None
        self._estimate_id: str | None = None

    def _assert_expected_artifact_hashes(self) -> None:
        """Fail before launch if a parent-provenance artifact changed in place."""
        executable = self.options.exe
        if executable is None:
            msg = "packaged executable is required for provenance verification"
            raise AssertionError(msg)
        expected_exe = self.options.expected_exe_sha256
        if expected_exe is not None and sha256_file(executable) != expected_exe:
            msg = "installed executable hash changed after installer resolution"
            raise AssertionError(msg)
        installer = self.options.installer
        expected_installer = self.options.expected_installer_sha256
        if expected_installer is not None and (
            installer is None or sha256_file(installer) != expected_installer
        ):
            msg = "installer hash changed after installed-parity preflight"
            raise AssertionError(msg)

    def checked(
        self,
        name: str,
        operation: Callable[[], Mapping[str, object] | None],
    ) -> None:
        """Run one check and convert its bounded result into a receipt event."""
        try:
            details = dict(operation() or {})
            _ = self.receipts.record(name, ReceiptStatus.PASSED, details)
        except FeatureUnavailableError as error:
            _ = self.receipts.record(
                name,
                ReceiptStatus.UNAVAILABLE,
                {"reason": str(error)},
            )
        except Exception as error:  # noqa: BLE001
            # A check receipt must capture every application/automation failure.
            details: dict[str, object] = {
                "error_type": type(error).__name__,
                "error": str(error),
            }
            if name == "launch-packaged-executable":
                details["qa_harness_sha256"] = self.receipts.qa_harness_sha256
            if self.page is not None:
                try:
                    screenshot = self.receipts.artifact_path(
                        "screenshots", f"failure-{name}.png"
                    )
                    _ = self.page.screenshot(path=str(screenshot), full_page=True)
                    details["screenshot"] = self.receipts.relative_artifact(screenshot)
                except Exception as screenshot_error:  # noqa: BLE001  # pragma: no cover
                    details["screenshot_error"] = str(screenshot_error)
            _ = self.receipts.record(name, ReceiptStatus.FAILED, details)

    def require_page(self) -> Page:
        """Return the attached page or report the unavailable inspection seam."""
        if self.page is None:
            msg = "WebView inspection is not attached"
            raise FeatureUnavailableError(msg)
        return self.page

    def invoke(
        self, command: str, args: Mapping[str, object] | None = None
    ) -> InvokeResult:
        """Invoke one domain command from inside the packaged Tauri WebView."""
        page = self.require_page()
        raw = cast(
            "dict[str, object]",
            page.evaluate(
                """async ({ command, args, timeoutMs }) => {
                    let timeoutHandle;
                    try {
                      const bridge = window.__TAURI_INTERNALS__;
                      const timeout = new Promise((_, reject) => {
                        timeoutHandle = setTimeout(
                          () => reject(new Error("QA_COMMAND_TIMEOUT")),
                          timeoutMs,
                        );
                      });
                      const value = await Promise.race([
                        bridge.invoke(command, args || {}),
                        timeout,
                      ]);
                      return { ok: true, value, error: null };
                    } catch (error) {
                      const hasMessage = error && typeof error === "object"
                        && "message" in error;
                      const message = hasMessage
                        ? String(error.message)
                        : String(error);
                      return { ok: false, value: null, error: message };
                    } finally {
                      clearTimeout(timeoutHandle);
                    }
                }""",
                {
                    "command": command,
                    "args": dict(args or {}),
                    "timeoutMs": self.options.timeout_seconds * 1000,
                },
            ),
        )
        return InvokeResult(
            ok=bool(raw.get("ok")),
            value=raw.get("value"),
            error=str(raw["error"]) if raw.get("error") is not None else None,
        )

    def require_command(
        self, command: str, args: Mapping[str, object] | None = None
    ) -> object:
        """Return a successful command value or classify its safe error."""
        result = self.invoke(command, args)
        if result.ok:
            return result.value
        error = result.error or "command failed without an error"
        if UNKNOWN_COMMAND.search(error):
            message = f"planned app command unavailable: {command}"
            raise FeatureUnavailableError(message)
        raise RuntimeError(error)

    def screenshot(self, name: str) -> str:
        """Capture a full-page screenshot and return its receipt-relative path."""
        page = self.require_page()
        path = self.receipts.artifact_path("screenshots", name)
        _ = page.screenshot(path=str(path), full_page=True)
        return self.receipts.relative_artifact(path)

    def launch(self) -> Mapping[str, object]:
        """Launch and identify the packaged executable and attached WebView."""
        self._assert_expected_artifact_hashes()
        self.page = self.session.start()
        executable = self.options.exe
        if executable is None:
            msg = "packaged executable is required for launch evidence"
            raise AssertionError(msg)
        details: dict[str, object] = {
            "pid": self.session.process.pid if self.session.process else None,
            "executable": executable.name,
            "executable_bytes": executable.stat().st_size,
            "executable_sha256": sha256_file(executable),
            "qa_harness_sha256": self.receipts.qa_harness_sha256,
            "devtools_port": self.session.devtools_port,
            "runtime_key_environment": False,
            "webview_url": self.page.url,
            "title": self.page.title(),
        }
        installer = self.options.installer
        if installer is not None:
            details["installer"] = installer.name
            details["installer_bytes"] = installer.stat().st_size
            details["installer_sha256"] = sha256_file(installer)
        return details

    def shell(self) -> Mapping[str, object]:
        """Verify the packaged shell opens on its catalog route."""
        page = self.require_page()
        page.get_by_role("heading", name="물품 검색", exact=True).wait_for()
        if page.locator('[data-route="catalog"]').count() != 1:
            msg = "catalog route did not become the unique active route"
            raise AssertionError(msg)
        page.locator(".app-brand").click()
        page.get_by_role("heading", name="문서 작성", exact=True).wait_for()
        page.get_by_role("button", name="물품 검색", exact=True).click()
        page.get_by_role("heading", name="물품 검색", exact=True).wait_for()
        return {
            "route": "catalog",
            "heading": "물품 검색",
            "home_logo_navigation": "passed",
            "screenshot": self.screenshot("startup-shell.png"),
        }

    def no_python_server(self) -> Mapping[str, object]:
        """Prove the packaged surface does not depend on legacy port 8765."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(1.0)
            connected = connection.connect_ex(("127.0.0.1", 8765)) == 0
        if connected:
            msg = "port 8765 is bound; packaged isolation cannot be established"
            raise AssertionError(msg)
        return {"port": 8765, "bound": False}

    def seed_copy(self) -> Mapping[str, object]:
        """Inspect the isolated first-start database copy and SQLite integrity."""
        candidates = sorted(self.state_root.rglob("g2b.sqlite3"))
        if len(candidates) != 1:
            msg = f"expected one isolated AppData database, found {len(candidates)}"
            raise AssertionError(msg)
        database = candidates[0]
        uri = f"file:{database.as_posix()}?mode=ro"
        with sqlite3.connect(
            uri, uri=True, timeout=self.options.timeout_seconds
        ) as connection:
            integrity = str(sqlite_scalar(connection, "PRAGMA integrity_check"))
            table_count = require_int(
                sqlite_scalar(
                    connection,
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'",
                ),
                "table count",
            )
            user_version = require_int(
                sqlite_scalar(connection, "PRAGMA user_version"), "user version"
            )
            journal_mode = str(sqlite_scalar(connection, "PRAGMA journal_mode"))
        if integrity != "ok" or table_count == 0:
            msg = "copied AppData database failed integrity or schema checks"
            raise AssertionError(msg)
        source_seed = (
            Path(__file__).resolve().parents[2]
            / "desktop"
            / "src-tauri"
            / "resources"
            / "seed.sqlite3"
        )
        source_archive = source_seed.with_suffix(".sqlite3.zip")
        details: dict[str, object] = {
            "app_data_relative_path": database.relative_to(self.state_root).as_posix(),
            "bytes": database.stat().st_size,
            "integrity": integrity,
            "journal_mode": journal_mode,
            "table_count": table_count,
            "user_version": user_version,
        }
        executable = self.options.exe
        if executable is None:
            msg = "packaged executable is required for seed verification"
            raise AssertionError(msg)
        packaged_archive = executable.parent / "resources" / "seed.sqlite3.zip"
        if (
            source_seed.is_file()
            and source_archive.is_file()
            and packaged_archive.is_file()
        ):
            source_archive_hash = sha256_file(source_archive)
            packaged_archive_hash = sha256_file(packaged_archive)
            if packaged_archive_hash != source_archive_hash:
                msg = "packaged seed archive differs from the verified source archive"
                raise AssertionError(msg)
            with zipfile.ZipFile(source_archive) as archive:
                if archive.namelist() != ["seed.sqlite3"]:
                    msg = "source seed archive must contain exactly seed.sqlite3"
                    raise AssertionError(msg)
                uncompressed_hasher = hashlib.sha256()
                with archive.open("seed.sqlite3") as source:
                    while chunk := source.read(1024 * 1024):
                        uncompressed_hasher.update(chunk)
            source_hash = sha256_file(source_seed)
            uncompressed_hash = uncompressed_hasher.hexdigest()
            if uncompressed_hash != source_hash:
                msg = "compressed seed does not expand to the verified source database"
                raise AssertionError(msg)
            copied_hash = sha256_file(database)
            details["source_archive_sha256"] = source_archive_hash
            details["packaged_archive_sha256"] = packaged_archive_hash
            details["uncompressed_seed_sha256"] = uncompressed_hash
            details["copied_sha256"] = copied_hash
            details["packaged_seed_exact"] = True
            details["copy_changed_after_startup"] = copied_hash != source_hash
        return details

    def catalog_search(self) -> Mapping[str, object]:
        """Search a seeded product and verify complete card metadata."""
        page = self.require_page()
        summary = page.locator(".catalog-summary")
        summary.get_by_text("검색 중").wait_for(state="hidden")
        cards = page.locator(".catalog-card")
        if cards.count() < 1:
            msg = "seeded catalog did not render a product card"
            raise AssertionError(msg)
        raw = self.require_command(
            "search_products",
            {
                "request": {
                    "company_name": "",
                    "query": "",
                    "sort": "price_asc",
                    "page": 1,
                }
            },
        )
        result = require_mapping(raw, "catalog page")
        items = require_mapping_list(result.get("items"), "catalog items")
        if not items:
            msg = "seeded catalog command returned no products"
            raise AssertionError(msg)
        cache = require_mapping(
            self.require_command("get_catalog_cache_status"),
            "catalog cache status",
        )
        if (
            cache.get("state") != "ready"
            or require_int(cache.get("contract_version"), "cache contract version") < 1
            or require_int(cache.get("cache_version"), "catalog cache version") < 1
            or not str(cache.get("release_identity", "")).strip()
        ):
            msg = "catalog cache did not expose a validated persistent version"
            raise AssertionError(msg)
        self._first_product = items[0]
        query = str(items[0].get("name", "")).strip()
        search = page.get_by_label("검색어", exact=True)
        search.fill(query)
        summary.get_by_text("검색 중").wait_for(state="hidden")
        if page.locator(".catalog-card").count() < 1:
            msg = "known seeded product was not found by name"
            raise AssertionError(msg)
        card_text = page.locator(".catalog-card").first.inner_text()
        for expected in ("규격", "원 /", "나라장터에서 보기", "리스트에 추가"):
            if expected not in card_text:
                message = f"product metadata/action missing: {expected}"
                raise AssertionError(message)
        return {
            "query_field": "name",
            "result_total": result.get("total_count"),
            "first_product_id": items[0].get("product_id"),
            "cache_contract_version": cache.get("contract_version"),
            "cache_version": cache.get("cache_version"),
            "cache_release_identity": cache.get("release_identity"),
            "rendered_cards": page.locator(".catalog-card").count(),
            "screenshot": self.screenshot("catalog-search.png"),
        }

    def catalog_sorts_paging_options(self) -> Mapping[str, object]:
        """Exercise four sorts, page bounds, deduplication, and relation tabs."""
        page = self.require_page()
        structured: dict[str, object] = {}
        for sort in ("price_asc", "price_desc", "name_asc", "product_id_asc"):
            _ = page.locator("#catalog-sort").select_option(sort)
            page.locator(".catalog-summary").get_by_text("검색 중").wait_for(
                state="hidden"
            )
            raw = self.require_command(
                "search_products",
                {
                    "request": {
                        "company_name": "",
                        "query": "",
                        "sort": sort,
                        "page": 1,
                    }
                },
            )
            result = require_mapping(raw, f"catalog sort {sort}")
            items = require_mapping_list(
                result.get("items"), f"catalog sort {sort} items"
            )
            ids = [str(item.get("product_id", "")) for item in items]
            if len(items) > CATALOG_PAGE_SIZE or len(ids) != len(set(ids)):
                msg = f"sort {sort} violated page size or deduplication"
                raise AssertionError(msg)
            structured[sort] = {
                "first_product_id": ids[0] if ids else None,
                "page_size": len(ids),
                "page_count": result.get("page_count"),
            }
        page.get_by_label("검색어", exact=True).fill(RELATION_FIXTURE_PRODUCT_ID)
        page.locator(".catalog-summary").get_by_text("검색 중").wait_for(state="hidden")
        page.locator(".catalog-card__select").first.click()
        panel = page.locator(".option-panel")
        panel.wait_for()
        tab_counts: dict[str, int] = {}
        for label in ("선택품목", "추가선택품목", "공사"):
            tab = page.get_by_role("tab", name=re.compile(f"^{label}"))
            tab.click()
            page.locator('.option-scroll[aria-busy="false"]').wait_for()
            tab_counts[label] = page.locator(".option-row").count()
        if sum(tab_counts.values()) == 0:
            msg = "known relation-bearing catalog product exposed no relation rows"
            raise AssertionError(msg)
        return {
            "sorts": structured,
            "relation_tabs": tab_counts,
            "virtual_rendered_cards": page.locator(".catalog-card").count(),
            "screenshot": self.screenshot("catalog-sorts-options.png"),
        }

    def estimate_crud(self) -> Mapping[str, object]:
        """Create, open, edit, and save an estimate through the desktop UI."""
        page = self.require_page()
        if self._first_product is None:
            msg = "catalog fixture product was not captured"
            raise FeatureUnavailableError(msg)
        page.get_by_role("button", name="물품 검색", exact=True).click()
        page.locator(".catalog-card").first.get_by_role(
            "button", name="리스트에 추가", exact=True
        ).click()
        status = page.get_by_role("status").filter(has_text="리스트에 추가함")
        status.wait_for()
        page.get_by_role("button", name="문서 작성", exact=True).click()
        page.get_by_role("heading", name="문서 작성", exact=True).wait_for()
        summary = page.locator(".estimate-summary")
        summary.first.wait_for()
        summary.first.get_by_role("button").first.click()
        page.locator(".document-table tbody tr").first.wait_for()
        table_columns = page.locator(".document-table col").count()
        if table_columns != LEGACY_DOCUMENT_COLUMN_COUNT:
            msg = (
                f"document table exposed {table_columns} columns, "
                f"not {LEGACY_DOCUMENT_COLUMN_COUNT}"
            )
            raise AssertionError(msg)
        if page.locator('input[type="number"]').count() != 0:
            msg = "removed quantity control is present in the packaged editor"
            raise AssertionError(msg)
        id_text = page.locator(".page-header__copy p").inner_text()
        match = re.search(r"문서 ID: ([0-9a-f]{32})", id_text)
        if match is None:
            msg = "estimate editor did not expose a 32-hex ID"
            raise AssertionError(msg)
        self._estimate_id = match.group(1)
        title_button = page.get_by_role("button", name=re.compile("^문서 제목 편집:"))
        title_button.click()
        title_input = page.get_by_label("문서 제목", exact=True)
        title_input.fill("QA parity estimate")
        title_input.press("Enter")
        page.get_by_text(re.compile(r"저장됨 · 리비전 \d+")).wait_for()
        return {
            "estimate_id": self._estimate_id,
            "title": "QA parity estimate",
            "line_count": page.locator(".document-table tbody tr").count(),
            "table_columns": table_columns,
            "quantity_controls": 0,
            "screenshot": self.screenshot("estimate-crud.png"),
        }

    def offline_local_crud_no_enqueue(self) -> Mapping[str, object]:
        """Prove native CRUD commits offline without creating recovery work."""
        page = self.require_page()
        context = self.session.context
        if context is None:
            msg = "Playwright browser context is unavailable"
            raise FeatureUnavailableError(msg)
        context.set_offline(True)
        try:
            page.get_by_role("button", name="문서 작성", exact=True).click()
            page.get_by_role("button", name="새 문서", exact=True).click()
            page.get_by_role("button", name=re.compile("^문서 제목 편집:")).click()
            title_input = page.get_by_label("문서 제목", exact=True)
            title_input.fill("QA offline local estimate")
            title_input.press("Enter")
            page.get_by_text(re.compile(r"저장됨 · 리비전 \d+")).wait_for()
            id_text = page.locator(".page-header__copy p").inner_text()
            match = re.search(r"문서 ID: ([0-9a-f]{32})", id_text)
            if match is None:
                msg = "offline-created estimate did not expose a 32-hex ID"
                raise AssertionError(msg)
            estimate_id = match.group(1)
            deleted = self.invoke("delete_estimate", {"id": estimate_id})
            if not deleted.ok:
                msg = deleted.error or "offline native delete failed"
                raise AssertionError(msg)
            page.get_by_role("button", name="문서 작성", exact=True).click()
            page.locator('[data-route="estimates"]').wait_for()
            queue_count = qa_replay_queue_count(self.state_root)
            if queue_count != 0:
                msg = f"native offline CRUD created {queue_count} replay mutations"
                raise AssertionError(msg)
            return {
                "estimate_id": estimate_id,
                "create_save_delete": "passed",
                "replay_queue_count": queue_count,
                "screenshot": self.screenshot("offline-local-crud.png"),
            }
        finally:
            context.set_offline(False)

    def _document_row_count(self) -> int:
        """Return the count of actual estimate rows, excluding the empty placeholder."""
        return (
            self.require_page()
            .locator(".document-table tbody tr:not(.document-empty-row)")
            .count()
        )

    def _estimate_revision(self) -> int:
        """Read the durable revision before arming a UI autosave transition."""
        if self._estimate_id is None:
            msg = "estimate CRUD did not retain an ID for picker autosave verification"
            raise FeatureUnavailableError(msg)
        document = require_mapping(
            self.require_command("read_estimate", {"id": self._estimate_id}),
            "picker estimate document",
        )
        return require_int(document.get("revision"), "picker estimate revision")

    def _arm_revision_advance(self, current_revision: int) -> None:
        """Subscribe to the exact visible autosave revision before a UI mutation."""
        page = self.require_page()
        page.evaluate(
            """(currentRevision) => {
                const state = document.querySelector('.estimate-save-state');
                if (!(state instanceof HTMLElement)) {
                  throw new Error('estimate autosave status is unavailable');
                }
                const revisionOf = () => {
                  const match = state.textContent?.match(
                    /저장됨\\s*·\\s*리비전\\s+(\\d+)/,
                  );
                  return match ? Number.parseInt(match[1], 10) : null;
                };
                if (revisionOf() !== currentRevision) {
                  throw new Error(
                    'estimate revision changed before autosave subscription',
                  );
                }
                window.__qaRevisionAdvance = new Promise((resolve) => {
                  const observer = new MutationObserver(() => {
                    const revision = revisionOf();
                    if (revision !== null && revision > currentRevision) {
                      observer.disconnect();
                      resolve(revision);
                    }
                  });
                  observer.observe(state, {
                    childList: true,
                    characterData: true,
                    subtree: true,
                  });
                });
            }""",
            current_revision,
        )

    def _await_revision_advance(self, current_revision: int) -> int:
        """Await the armed autosave state change with a bounded event timeout."""
        value = cast(
            "object",
            self.require_page().evaluate(
                """async ({ currentRevision, timeoutMs }) => {
                const pending = window.__qaRevisionAdvance;
                if (!(pending instanceof Promise)) {
                  throw new Error('estimate autosave transition was not armed');
                }
                const timeout = new Promise((_, reject) => {
                  globalThis.setTimeout(
                    () => reject(new Error('QA_AUTOSAVE_REVISION_TIMEOUT')),
                    timeoutMs,
                  );
                });
                try {
                  return await Promise.race([pending, timeout]);
                } finally {
                  delete window.__qaRevisionAdvance;
                }
            }""",
                {
                    "currentRevision": current_revision,
                    "timeoutMs": self.options.timeout_seconds * 1000,
                },
            ),
        )
        revision = require_int(value, "autosaved estimate revision")
        if revision != current_revision + 1:
            msg = (
                "picker autosave did not advance exactly one revision: "
                f"{current_revision} -> {revision}"
            )
            raise AssertionError(msg)
        return revision

    def _remove_all_document_rows(self) -> int:
        """Use the packaged UI to establish an empty document before picker coverage."""
        removed = 0
        while self._document_row_count() > 0:
            previous_revision = self._estimate_revision()
            self._arm_revision_advance(previous_revision)
            self.require_page().locator(
                ".document-table tbody tr:not(.document-empty-row)"
            ).first.get_by_role(
                "button", name=re.compile("행 삭제$", re.IGNORECASE)
            ).click()
            _ = self._await_revision_advance(previous_revision)
            removed += 1
        return removed

    def _assert_picker_company_results(self, dialog: Locator) -> tuple[int, int]:
        """Prove each rendered picker card comes from the preferred-company query."""
        dialog.locator(".estimate-picker__summary").get_by_text("검색 중").wait_for(
            state="hidden"
        )
        picker_page = require_mapping(
            self.require_command(
                "search_products",
                {
                    "request": {
                        "company_name": PREFERRED_COMPANY,
                        "query": "",
                        "sort": "price_asc",
                        "page": 1,
                    }
                },
            ),
            "picker company page",
        )
        picker_items = require_mapping_list(picker_page.get("items"), "picker items")
        if not picker_items:
            msg = "picker company query returned no seeded products"
            raise AssertionError(msg)
        if any(item.get("company_name") != PREFERRED_COMPANY for item in picker_items):
            msg = "picker company query returned a product outside 주식회사 코리아넷"
            raise AssertionError(msg)
        picker_cards = dialog.locator(".estimate-picker__product")
        picker_cards.first.wait_for()
        if picker_cards.count() != len(picker_items):
            msg = (
                "picker rendered a different number of products than its company query"
            )
            raise AssertionError(msg)
        for index, product in enumerate(picker_items):
            expected_values = (
                str(product.get("name", "")),
                str(product.get("spec", "")),
                f"{require_int(product.get('price_won'), 'picker product price'):,}원",
            )
            card_text = picker_cards.nth(index).inner_text()
            if any(value not in card_text for value in expected_values):
                msg = "picker rendered a product that does not match its company query"
                raise AssertionError(msg)
        return len(picker_items), picker_cards.count()

    def _exercise_picker_dismissals(
        self, dialog: Locator, opener: Locator
    ) -> Mapping[str, object]:
        """Check non-modal focus behavior through Escape and an outside pointer."""
        page = self.require_page()
        if dialog.get_attribute("aria-modal") != "false":
            msg = "estimate picker regressed to a modal dialog"
            raise AssertionError(msg)
        if page.locator(".estimate-picker-backdrop").count() != 0:
            msg = "non-modal estimate picker rendered a blocking backdrop"
            raise AssertionError(msg)
        search = page.get_by_role("searchbox", name="검색어", exact=True)
        focused_inside = cast(
            "bool",
            search.evaluate("(element) => element === document.activeElement"),
        )
        if not focused_inside:
            msg = "estimate picker did not focus its search input"
            raise AssertionError(msg)
        screenshot = self.screenshot("estimate-picker-nonmodal.png")
        page.keyboard.press("Escape")
        dialog.wait_for(state="hidden")
        if not search.evaluate("(element) => element === document.activeElement"):
            msg = "estimate picker did not preserve search focus after Escape"
            raise AssertionError(msg)
        opener.click()
        dialog.wait_for()
        outside = page.locator(".estimate-toolbar__back")
        outside.focus()
        outside_event_dispatched = cast(
            "bool",
            outside.evaluate(
                """(element) => element.dispatchEvent(
                    new PointerEvent('pointerdown', { bubbles: true })
                )"""
            ),
        )
        dialog.wait_for(state="hidden")
        if not outside.evaluate("(element) => element === document.activeElement"):
            msg = "outside dismissal stole focus from the active editor control"
            raise AssertionError(msg)
        return {
            "focus_inside": focused_inside,
            "non_modal": True,
            "escape_dismissal": "passed",
            "outside_dismissal": "passed",
            "outside_event_dispatched": outside_event_dispatched,
            "focus_preserved": True,
            "screenshot": screenshot,
        }

    def _add_first_picker_main_item(
        self,
        dialog: Locator,
        opener: Locator,
        *,
        expected_card_text: str | None = None,
    ) -> tuple[int, str]:
        """Add the first picker main item and await its exact persisted revision."""
        opener.click()
        dialog.wait_for()
        card = dialog.locator(".estimate-picker__product").first
        card.wait_for()
        card_text = card.inner_text()
        if expected_card_text is not None and card_text != expected_card_text:
            msg = "picker reordered its first main item before fixture restoration"
            raise AssertionError(msg)
        previous_revision = self._estimate_revision()
        self._arm_revision_advance(previous_revision)
        card.get_by_role("button", name="본품 추가", exact=True).click()
        return self._await_revision_advance(previous_revision), card_text

    def _picker_ui_add_remove(
        self, dialog: Locator, opener: Locator
    ) -> Mapping[str, object]:
        """Prove zero rows, then restore one durable UI row for following checks."""
        page = self.require_page()
        added_revision, first_card_text = self._add_first_picker_main_item(
            dialog, opener
        )
        if self._document_row_count() != 1:
            msg = "adding one picker main item did not create exactly one document row"
            raise AssertionError(msg)
        previous_remove_revision = self._estimate_revision()
        if previous_remove_revision != added_revision:
            msg = "picker add revision did not persist before the UI removal"
            raise AssertionError(msg)
        dialog.get_by_role("button", name="검색 닫기", exact=True).click()
        dialog.wait_for(state="hidden")
        self._arm_revision_advance(previous_remove_revision)
        rows = page.locator(".document-table tbody tr:not(.document-empty-row)")
        rows.first.get_by_role(
            "button", name=re.compile("행 삭제$", re.IGNORECASE)
        ).click()
        removed_revision = self._await_revision_advance(previous_remove_revision)
        if self._document_row_count() != 0:
            msg = (
                "removing the picker main item did not return the document to zero rows"
            )
            raise AssertionError(msg)
        replay_queue_count = qa_replay_queue_count(self.state_root)
        reconciliation = self._reconciliation_status("idle", 0)
        if replay_queue_count != 0:
            msg = f"picker UI mutations created {replay_queue_count} replay mutations"
            raise AssertionError(msg)

        comparison_fixture_revision, _ = self._add_first_picker_main_item(
            dialog,
            opener,
            expected_card_text=first_card_text,
        )
        if self._document_row_count() != 1:
            msg = "picker fixture restoration did not create exactly one document row"
            raise AssertionError(msg)
        comparison_fixture_queue_count = qa_replay_queue_count(self.state_root)
        if comparison_fixture_queue_count != 0:
            msg = (
                "picker fixture restoration created "
                f"{comparison_fixture_queue_count} replay mutations"
            )
            raise AssertionError(msg)
        dialog.get_by_role("button", name="검색 닫기", exact=True).click()
        dialog.wait_for(state="hidden")
        return {
            "add_revision": added_revision,
            "remove_revision": removed_revision,
            "rows_after_remove": 0,
            "replay_queue_count": replay_queue_count,
            "reconciliation": reconciliation,
            "comparison_fixture_revision": comparison_fixture_revision,
            "rows_for_following_checks": 1,
            "comparison_fixture_replay_queue_count": comparison_fixture_queue_count,
        }

    def picker_modal_interactions(self) -> Mapping[str, object]:
        """Exercise picker provenance, focus semantics, and durable UI add/remove."""
        initial_rows_removed = self._remove_all_document_rows()
        page = self.require_page()
        opener = page.get_by_role("button", name="내역 추가", exact=True)
        opener.click()
        dialog = page.get_by_role("dialog", name="물품 검색 결과")
        dialog.wait_for()
        company_query_result_count, rendered_company_results = (
            self._assert_picker_company_results(dialog)
        )
        interactions = self._exercise_picker_dismissals(dialog, opener)
        ui_mutation = self._picker_ui_add_remove(dialog, opener)
        return {
            **interactions,
            **ui_mutation,
            "company_name": PREFERRED_COMPANY,
            "company_query_result_count": company_query_result_count,
            "rendered_company_results": rendered_company_results,
            "initial_rows_removed_via_ui": initial_rows_removed,
        }

    def comparison_export_clipboard(self) -> Mapping[str, object]:
        """Refresh real comparisons, copy 17 columns, and export a valid XLSX."""
        if self._estimate_id is None:
            msg = "estimate CRUD did not retain an ID for export verification"
            raise FeatureUnavailableError(msg)
        page = self.require_page()
        page.get_by_role("button", name="비교군 새로고침", exact=True).click()
        page.get_by_role("button", name="새로고침 완료", exact=True).wait_for()
        comparison_links = page.locator(".document-product-link")
        comparison_links.first.wait_for()
        if comparison_links.count() < COMPARISON_SLOT_COUNT:
            msg = "comparison refresh did not render complete A/B/C product links"
            raise AssertionError(msg)

        page.get_by_role("button", name="표 복사", exact=True).click()
        page.get_by_text(re.compile(r"표 복사됨 · \d+행")).wait_for()
        clipboard_text = read_windows_clipboard_text().strip()
        clipboard_rows = clipboard_text.splitlines()
        if not clipboard_rows:
            msg = "clipboard command produced no TSV rows"
            raise AssertionError(msg)
        clipboard_columns = len(clipboard_rows[0].split("\t"))
        if clipboard_columns != LEGACY_CLIPBOARD_COLUMN_COUNT:
            msg = (
                f"clipboard row exposed {clipboard_columns} columns, "
                f"not {LEGACY_CLIPBOARD_COLUMN_COUNT}"
            )
            raise AssertionError(msg)

        page.get_by_role("button", name="XLSX 내보내기", exact=True).click()
        page.get_by_text(re.compile(r"XLSX 저장됨 · .+\.xlsx")).wait_for()
        exported = self.invoke("export_estimate_workbook", {"id": self._estimate_id})
        if not exported.ok or not isinstance(exported.value, Mapping):
            msg = exported.error or "workbook export returned no typed receipt"
            raise AssertionError(msg)
        export_value = cast("Mapping[str, object]", exported.value)
        path_value = export_value.get("path")
        if not isinstance(path_value, str):
            msg = "workbook export receipt did not include a path"
            raise TypeError(msg)
        workbook_path = Path(path_value)
        if not workbook_path.is_file():
            msg = f"exported workbook does not exist: {workbook_path}"
            raise AssertionError(msg)
        with zipfile.ZipFile(workbook_path) as workbook:
            if "xl/workbook.xml" not in workbook.namelist():
                msg = "exported workbook is not a complete OOXML workbook"
                raise AssertionError(msg)
        export_artifact = self.receipts.artifact_path("exports", workbook_path.name)
        _ = shutil.copy2(workbook_path, export_artifact)
        return {
            "comparison_links": comparison_links.count(),
            "clipboard_rows": len(clipboard_rows),
            "clipboard_columns": clipboard_columns,
            "export_artifact": self.receipts.relative_artifact(export_artifact),
            "export_bytes": export_artifact.stat().st_size,
            "export_sha256": sha256_file(export_artifact),
            "screenshot": self.screenshot("comparison-export-clipboard.png"),
        }

    def data_status_and_operations(self) -> Mapping[str, object]:
        """Verify seven local counts and explicit remote operation boundaries."""
        page = self.require_page()
        page.get_by_role("button", name="데이터 상태", exact=True).click()
        page.get_by_role("heading", name="데이터 상태", exact=True).wait_for()
        _ = page.locator(".status-panel").get_attribute("aria-busy")
        raw = self.require_command("get_data_status")
        status = require_mapping(raw, "data status")
        missing = [key for key in DATA_COUNT_KEYS if key not in status]
        if missing:
            msg = "data status omitted count fields: " + ", ".join(missing)
            raise AssertionError(msg)
        if page.locator(".data-count").count() != len(DATA_COUNT_KEYS):
            msg = "Data view did not render seven counts"
            raise AssertionError(msg)
        diagnostics = self.invoke("run_data_diagnostics")
        sync = self.invoke("run_data_sync")
        return {
            "counts": {key: status[key] for key in DATA_COUNT_KEYS},
            "ready": status.get("ready"),
            "readiness": status.get("readiness"),
            "diagnostics": command_boundary_summary(diagnostics),
            "sync": command_boundary_summary(sync),
            "screenshot": self.screenshot("data-status.png"),
        }

    def planned_state_commands(self) -> Mapping[str, object]:
        """Classify all planned state/replay commands without hiding absences."""
        unavailable: list[str] = []
        results: dict[str, object] = {}
        safe_args: dict[str, Mapping[str, object]] = {
            "save_desktop_view": {"state": {"route": "data", "path": "/data"}},
            "resolve_reconciliation_conflict": {
                "request": {"sequence": 0, "resolution": "keep-local"}
            },
        }
        for command in PLANNED_COMMANDS:
            result = self.invoke(command, safe_args.get(command))
            summary = command_boundary_summary(result)
            results[command] = summary
            if summary == "unavailable":
                unavailable.append(command)
        if unavailable:
            message = "planned app commands unavailable: " + ", ".join(unavailable)
            raise FeatureUnavailableError(message)
        return results

    def restart_restore(self) -> Mapping[str, object]:
        """Restart the executable and verify durable catalog view restoration."""
        page = self.require_page()
        page.get_by_role("button", name="물품 검색", exact=True).click()
        search = page.get_by_label("검색어", exact=True)
        search.fill(
            str(self._first_product.get("name", "")) if self._first_product else ""
        )
        page.locator(".catalog-summary").get_by_text("검색 중").wait_for(state="hidden")
        before = search.input_value()
        stop_details = self.session.stop()
        self.page = None
        self.page = self.session.start()
        restored = self.require_page().get_by_label("검색어", exact=True).input_value()
        if restored != before:
            msg = (
                "catalog query was not restored across restart: "
                f"{before!r} != {restored!r}"
            )
            raise AssertionError(msg)
        return {
            "query_restored": True,
            "stop": stop_details,
            "screenshot": self.screenshot("restart-restored.png"),
        }

    def offline_cached_catalog(self) -> Mapping[str, object]:
        """Dispatch an offline event and verify the warm catalog remains visible."""
        page = self.require_page()
        context = self.session.context
        if context is None:
            msg = "Playwright browser context is unavailable"
            raise FeatureUnavailableError(msg)
        page.get_by_role("button", name="물품 검색", exact=True).click()
        cards = page.locator(".catalog-card")
        cards.first.wait_for()
        cards_before = cards.count()
        if cards_before == 0:
            msg = "offline cache check requires at least one settled catalog card"
            raise AssertionError(msg)
        context.set_offline(True)
        try:
            page.get_by_text("오프라인 상태", exact=True).wait_for()
            cards_offline = cards.count()
            if cards_offline != cards_before:
                msg = (
                    f"offline catalog changed from {cards_before} "
                    f"cards to {cards_offline}"
                )
                raise AssertionError(msg)
            screenshot = self.screenshot("offline-catalog.png")
        finally:
            context.set_offline(False)
        return {
            "cards_before": cards_before,
            "cards_offline": cards_offline,
            "screenshot": screenshot,
        }

    def _reconciliation_status(
        self, expected_state: str, expected_queue_count: int
    ) -> dict[str, object]:
        """Return an exact reconciliation state from the live packaged command."""
        status = require_mapping(
            self.require_command("get_reconciliation_status"),
            "reconciliation status",
        )
        actual_count = require_int(status.get("queued_count"), "queued change count")
        if (
            status.get("state") != expected_state
            or actual_count != expected_queue_count
        ):
            msg = (
                "unexpected reconciliation status: "
                f"state={status.get('state')!r}, queued_count={actual_count}"
            )
            raise AssertionError(msg)
        if status.get("conflicts") != []:
            msg = "replay fixture unexpectedly produced a reconciliation conflict"
            raise AssertionError(msg)
        return status

    def _assert_qa_replay_estimate(self) -> dict[str, object]:
        """Assert that the queued create mutation materialized exactly once."""
        document = require_mapping(
            self.require_command("read_estimate", {"id": QA_REPLAY_ESTIMATE_ID}),
            "replayed estimate",
        )
        lines = require_mapping_list(document.get("lines"), "replayed estimate lines")
        summaries = require_mapping_list(
            self.require_command("list_estimates"), "estimate summaries"
        )
        matching_summaries = [
            summary
            for summary in summaries
            if summary.get("id") == QA_REPLAY_ESTIMATE_ID
        ]
        expected_line: dict[str, object] = {
            "id": QA_REPLAY_LINE_ID,
            "line_no": 1,
            "line_kind": "main",
            "product_id": "24492324",
            "parent_product_id": None,
            "relation_id": None,
            "offer_operation": None,
            "offer_key": None,
            "item_name_snapshot": "QA replay item",
            "spec_snapshot": "QA replay specification",
            "company_snapshot": "QA replay company",
            "unit_snapshot": "EA",
            "unit_price_won_snapshot": 1000,
            "quantity": "1",
            "comparisons": [],
        }
        if (
            document.get("id") != QA_REPLAY_ESTIMATE_ID
            or document.get("title") != "QA offline replay estimate"
            or document.get("template_sha256") != QA_REPLAY_TEMPLATE_SHA256
            or document.get("revision") != 1
            or lines != [expected_line]
            or len(matching_summaries) != 1
            or matching_summaries[0].get("revision") != 1
            or matching_summaries[0].get("line_count") != 1
            or matching_summaries[0].get("total_won") != QA_REPLAY_TOTAL_WON
        ):
            msg = "queued estimate mutation was not materialized exactly once"
            raise AssertionError(msg)
        return document

    def offline_replay_restart_exactly_once(self) -> Mapping[str, object]:
        """Replay one stopped-app mutation and prove restart idempotency."""
        if self.session.process is None:
            msg = "the packaged app must be running before replay injection is prepared"
            raise FeatureUnavailableError(msg)
        initial_stop = self.session.stop()
        self.page = None
        sequence = inject_qa_replay_mutation(self.state_root)
        stopped_queue_count = qa_replay_queue_count(self.state_root)
        if stopped_queue_count != 1:
            msg = f"injected QA replay queue count was {stopped_queue_count}, not one"
            raise AssertionError(msg)

        self.page = self.session.start()
        page = self.require_page()
        banner = page.locator(".reconciliation-banner")
        banner.get_by_text("동기화 대기 중", exact=True).wait_for()
        banner.get_by_text(
            "1건의 변경사항이 이 기기에 안전하게 저장되어 있습니다.", exact=True
        ).wait_for()
        queued_status = self._reconciliation_status("queued", 1)
        banner.get_by_role("button", name="다시 확인", exact=True).click()
        banner.wait_for(state="hidden")
        replayed_status = self._reconciliation_status("idle", 0)
        replayed_document = self._assert_qa_replay_estimate()

        replay_stop = self.session.stop()
        self.page = None
        stopped_post_replay_count = qa_replay_queue_count(self.state_root)
        if stopped_post_replay_count != 0:
            msg = "replayed QA mutation remained in the stopped-app durable queue"
            raise AssertionError(msg)

        self.page = self.session.start()
        page = self.require_page()
        page.locator(".reconciliation-banner").wait_for(state="hidden")
        restarted_status = self._reconciliation_status("idle", 0)
        restarted_document = self._assert_qa_replay_estimate()
        if restarted_document != replayed_document:
            msg = (
                "replayed estimate changed after a restart with an empty durable queue"
            )
            raise AssertionError(msg)
        return {
            "mutation_sequence": sequence,
            "replay_database": "qa-state/app-data/offline-replay.sqlite3",
            "queued_status": queued_status,
            "replay_trigger": "reconciliation banner retry",
            "replayed_status": replayed_status,
            "restarted_status": restarted_status,
            "exact_once_materialization": True,
            "initial_stop": initial_stop,
            "replay_stop": replay_stop,
            "screenshot": self.screenshot("offline-replay-restarted.png"),
        }

    def bad_inputs_and_nine_line_boundary(self) -> Mapping[str, object]:
        """Exercise hostile search, the removed quantity surface, and the tenth add."""
        page = self.require_page()
        page.get_by_role("button", name="물품 검색", exact=True).click()
        search = page.get_by_label("검색어", exact=True)
        search.fill("'\"<>%_QA_NO_MATCH_\u0000".replace("\u0000", ""))
        page.locator(".catalog-summary").get_by_text("검색 중").wait_for(state="hidden")
        page.get_by_text("검색 결과 없음", exact=True).wait_for()
        search.fill("")
        page.locator(".catalog-summary").get_by_text("검색 중").wait_for(state="hidden")
        add = page.locator(".catalog-card").first.get_by_role(
            "button", name="리스트에 추가", exact=True
        )
        last_status = ""
        for _index in range(10):
            add.click()
            status = page.locator(".state-message").first
            status.wait_for()
            last_status = status.inner_text()
            if "최대 9개" in last_status or "at most nine" in last_status:
                break
        if "최대 9개" not in last_status and "at most nine" not in last_status:
            msg = "tenth catalog add did not expose the nine-line boundary"
            raise AssertionError(msg)
        page.get_by_role("button", name="문서 작성", exact=True).click()
        page.locator(".estimate-summary").first.get_by_role("button").first.click()
        if page.locator('input[type="number"]').count() != 0:
            msg = "removed quantity control is still present in the packaged editor"
            raise AssertionError(msg)
        return {
            "bad_search": "empty-state",
            "line_boundary": last_status,
            "quantity_controls": 0,
            "screenshot": self.screenshot("adversarial-inputs.png"),
        }

    def revision_conflict(self) -> Mapping[str, object]:
        """Create an exact stale-revision conflict and verify UI reconciliation."""
        page = self.require_page()
        id_text = page.locator(".page-header__copy p").inner_text()
        match = re.search(r"문서 ID: ([0-9a-f]{32})", id_text)
        if match is None:
            msg = "no estimate is open for conflict exercise"
            raise FeatureUnavailableError(msg)
        estimate_id = match.group(1)
        document = require_mapping(
            self.require_command("read_estimate", {"id": estimate_id}),
            "estimate document",
        )
        revision = require_int(document["revision"], "estimate revision")
        request = {
            "expected_revision": revision,
            "title": f"external-{revision}",
            "lines": [
                strip_line_for_update(item)
                for item in require_mapping_list(
                    document.get("lines"), "estimate lines"
                )
            ],
            "comparisons": flatten_comparisons(document),
        }
        _ = self.require_command(
            "update_estimate", {"id": estimate_id, "request": request}
        )
        title_button = page.get_by_role("button", name=re.compile("^문서 제목 편집:"))
        title_button.click()
        title_input = page.get_by_label("문서 제목", exact=True)
        title_input.fill("stale local edit")
        title_input.press("Enter")
        page.get_by_role("alert").filter(has_text="다른 창에서").wait_for()
        return {
            "estimate_id": estimate_id,
            "stale_revision": revision,
            "conflict_visible": True,
            "screenshot": self.screenshot("revision-conflict.png"),
        }

    def forbidden_generic_commands(self) -> Mapping[str, object]:
        """Prove generic SQL, shell, file, HTTP, and file-URL seams reject."""
        results: dict[str, object] = {}
        for command in ("shell_execute", "fs_read_file", "http_request", "sql_execute"):
            result = self.invoke(
                command,
                {"path": "C:/Windows/win.ini", "url": "https://example.invalid"},
            )
            if result.ok:
                message = f"forbidden generic command unexpectedly succeeded: {command}"
                raise AssertionError(message)
            results[command] = "rejected"
        invalid = self.invoke(
            "open_product", {"detailUrl": "file:///C:/Windows/win.ini"}
        )
        if invalid.ok:
            msg = "file URL crossed the fixed product-open boundary"
            raise AssertionError(msg)
        results["file_url"] = "rejected"
        return results

    def run(self) -> None:
        """Execute exactly the checks registered for the selected scenario."""
        self.checked("launch-packaged-executable", self.launch)
        if self.page is None:
            return
        self.checked("shell-startup", self.shell)
        self.checked("no-python-server", self.no_python_server)
        self.checked("seed-copy", self.seed_copy)
        self.checked("catalog-search-metadata", self.catalog_search)
        if self.options.scenario == "startup-catalog":
            self.checked("data-status-offline-local", self.data_status_and_operations)
            self.checked("planned-command-availability", self.planned_state_commands)
        elif self.options.scenario == "full-parity":
            self.checked(
                "search-sorts-paging-options", self.catalog_sorts_paging_options
            )
            self.checked("estimate-crud", self.estimate_crud)
            self.checked("picker-modal-interactions", self.picker_modal_interactions)
            self.checked(
                "comparison-export-clipboard", self.comparison_export_clipboard
            )
            self.checked(
                "offline-local-crud-no-enqueue",
                self.offline_local_crud_no_enqueue,
            )
            self.checked("data-status-operations", self.data_status_and_operations)
            self.checked("offline-and-cached-catalog", self.offline_cached_catalog)
            self.checked(
                "offline-replay-restart-exactly-once",
                self.offline_replay_restart_exactly_once,
            )
            self.checked("restart-and-state-restore", self.restart_restore)
            self.checked("planned-command-availability", self.planned_state_commands)
        else:
            self.checked(
                "adversarial-bad-inputs-nine-lines",
                self.bad_inputs_and_nine_line_boundary,
            )
            self.checked("adversarial-revision-conflict", self.revision_conflict)
            self.checked("adversarial-offline-cache", self.offline_cached_catalog)
            self.checked(
                "adversarial-forbidden-commands", self.forbidden_generic_commands
            )
            self.checked("adversarial-restart", self.restart_restore)
            self.checked("planned-command-availability", self.planned_state_commands)

    def cleanup(self) -> Mapping[str, object]:
        """Stop automation/processes and remove isolated QA state by default."""
        stop_details = self.session.stop()
        retained = self.options.keep_qa_data
        removed = False
        if not retained and self.state_root.exists():
            shutil.rmtree(self.state_root)
            removed = not self.state_root.exists()
        return {
            "process": stop_details,
            "qa_state": "retained" if retained else "removed",
            "path_exists_after_cleanup": self.state_root.exists(),
            "removed": removed,
        }


def sqlite_scalar(connection: sqlite3.Connection, statement: str) -> object:
    """Return one SQLite scalar while rejecting malformed result shapes."""
    row = cast("tuple[object, ...] | None", connection.execute(statement).fetchone())
    if row is None or not row:
        message = f"SQLite statement returned no scalar: {statement}"
        raise RuntimeError(message)
    return row[0]


def require_int(value: object, label: str) -> int:
    """Narrow a decoded or SQLite value to a non-boolean integer."""
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"{label} was not an integer"
        raise TypeError(message)
    return value


def require_mapping(value: object, label: str) -> dict[str, object]:
    """Narrow a decoded JSON value to an object mapping."""
    if not isinstance(value, dict):
        message = f"{label} was not a JSON object"
        raise TypeError(message)
    mapping = cast("Mapping[object, object]", value)
    return {str(key): item for key, item in mapping.items()}


def require_mapping_list(value: object, label: str) -> list[dict[str, object]]:
    """Narrow a decoded JSON value to an array of object mappings."""
    if not isinstance(value, list):
        message = f"{label} was not a JSON object array"
        raise TypeError(message)
    sequence = cast("Sequence[object]", value)
    return [require_mapping(item, label) for item in sequence]


def command_boundary_summary(result: InvokeResult) -> object:
    """Return a structured, secret-safe summary of one command result."""
    if result.ok:
        return result.value if result.value is not None else "complete"
    if result.error and UNKNOWN_COMMAND.search(result.error):
        return "unavailable"
    return {"state": "safe-error", "message": result.error or "unknown error"}


def strip_line_for_update(line: Mapping[str, object]) -> dict[str, object]:
    """Remove command-owned projection fields from an estimate line."""
    return {
        key: value
        for key, value in line.items()
        if key not in {"line_no", "comparisons"}
    }


def flatten_comparisons(document: Mapping[str, object]) -> list[dict[str, object]]:
    """Flatten line comparison arrays into the update-command request shape."""
    comparisons: list[dict[str, object]] = []
    for line in require_mapping_list(document.get("lines"), "estimate lines"):
        comparisons.extend(
            require_mapping_list(line.get("comparisons", []), "line comparisons")
        )
    return comparisons


def sha256_file(path: Path) -> str:
    """Hash a potentially large artifact without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def loopback_port_is_open(port: int) -> bool:
    """Return whether one loopback TCP port accepts a connection right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(1.0)
        return connection.connect_ex(("127.0.0.1", port)) == 0


@dataclass(frozen=True)
class InstalledApplication:
    """The one installed executable resolved from the authoritative HKCU entry."""

    install_location: Path
    executable: Path
    uninstaller: Path


class InstalledApplicationRegistry(Protocol):
    """Boundary for the authoritative current-user NSIS uninstall entry."""

    def installed_application(self) -> InstalledApplication | None:
        """Return the installed app, or none if its uninstall entry is absent."""
        ...


class InstallCompletionWatcher(Protocol):
    """One event source for uninstall registry and directory changes."""

    def wait_for_change(self, timeout_ms: int) -> bool:
        """Wait for the next registry or filesystem change without polling."""
        ...

    def close(self) -> None:
        """Release every watcher handle."""
        ...


class InstallCompletionWatcherFactory(Protocol):
    """Construct a pre-armed completion watcher before running uninstall.exe."""

    def create(self, install_parent: Path) -> InstallCompletionWatcher:
        """Watch the installed directory parent and uninstall registry parent."""
        ...


class NativeCommandExecutor(Protocol):
    """Run an executable directly with an argument vector and no shell."""

    def run(self, command: Sequence[str], *, timeout_seconds: int, cwd: Path) -> int:
        """Run one command and return its exact process exit code."""
        ...


@final
class WindowsNativeCommandExecutor:
    """Direct Python subprocess executor for NSIS setup and uninstall binaries."""

    def run(self, command: Sequence[str], *, timeout_seconds: int, cwd: Path) -> int:
        """Invoke an exact native executable vector without a shell or path rewrite."""
        completed = subprocess.run(  # noqa: S603
            list(command),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
        return completed.returncode


def _required_registry_string(values: Mapping[str, object], name: str) -> str:
    """Return one non-empty string registry value or reject the malformed entry."""
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        msg = f"uninstall registry entry is missing a non-empty {name} value"
        raise RuntimeError(msg)
    return value.strip()


def _uninstaller_from_value(value: str, install_location: Path) -> Path:
    """Extract the executable-only NSIS uninstaller boundary without shell parsing."""
    trimmed = value.strip()
    if trimmed.startswith('"'):
        closing = trimmed.find('"', 1)
        if closing < 1 or trimmed[closing + 1 :].strip():
            msg = "uninstall registry command must contain only one quoted executable"
            raise RuntimeError(msg)
        candidate = trimmed[1:closing]
    else:
        if any(character.isspace() for character in trimmed):
            msg = "uninstall registry command must contain only one executable"
            raise RuntimeError(msg)
        candidate = trimmed
    uninstaller = Path(candidate).resolve()
    resolved_location = install_location.resolve()
    if (
        uninstaller.suffix.lower() != ".exe"
        or not uninstaller.is_relative_to(resolved_location)
        or not uninstaller.is_file()
    ):
        msg = "uninstall registry command does not name an installed uninstaller.exe"
        raise RuntimeError(msg)
    return uninstaller


def _registry_path_value(value: str) -> str:
    """Unwrap one optionally quoted registry path without accepting arguments."""
    trimmed = value.strip()
    if not trimmed.startswith('"'):
        if '"' in trimmed:
            msg = "registry path contains an unmatched quote"
            raise RuntimeError(msg)
        return trimmed
    if not trimmed.endswith('"') or '"' in trimmed[1:-1]:
        msg = "quoted registry path must contain exactly one path"
        raise RuntimeError(msg)
    unwrapped = trimmed[1:-1]
    if not unwrapped:
        msg = "quoted registry path cannot be empty"
        raise RuntimeError(msg)
    return unwrapped


def installed_application_from_registry_values(
    values: Mapping[str, object],
) -> InstalledApplication:
    """Resolve only the installed EXE named by the HKCU InstallLocation authority."""
    install_location = Path(
        _registry_path_value(_required_registry_string(values, "InstallLocation"))
    ).resolve()
    if not install_location.is_absolute() or not install_location.is_dir():
        msg = "uninstall registry InstallLocation is not an existing absolute directory"
        raise RuntimeError(msg)
    executable = (install_location / INSTALLED_EXECUTABLE_NAME).resolve()
    if (
        not executable.is_relative_to(install_location)
        or not executable.is_file()
        or executable.suffix.lower() != ".exe"
    ):
        msg = "uninstall registry InstallLocation does not contain the installed EXE"
        raise RuntimeError(msg)
    return InstalledApplication(
        install_location=install_location,
        executable=executable,
        uninstaller=_uninstaller_from_value(
            _required_registry_string(values, "UninstallString"), install_location
        ),
    )


@final
class WindowsUninstallRegistry:
    """Read the fixed Tauri NSIS current-user uninstall authority on Windows."""

    def installed_application(self) -> InstalledApplication | None:
        """Read and validate HKCU's exact uninstall key and its InstallLocation."""
        if sys.platform != "win32":
            msg = "installed NSIS provenance verification requires Windows"
            raise FeatureUnavailableError(msg)
        import winreg  # noqa: PLC0415

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                UNINSTALL_REGISTRY_SUBKEY,
                0,
                access,
            ) as key:
                values: dict[str, object] = {}
                for name in ("InstallLocation", "UninstallString", "DisplayName"):
                    try:
                        values[name] = winreg.QueryValueEx(key, name)[0]
                    except FileNotFoundError:
                        continue
        except FileNotFoundError:
            return None
        return installed_application_from_registry_values(values)


@final
class WindowsInstallationCompletionWatcher:
    """Wait for NSIS registry and install-parent events without polling."""

    _FILE_NOTIFY_CHANGE_FILE_NAME: Final = 0x00000001
    _FILE_NOTIFY_CHANGE_DIR_NAME: Final = 0x00000002
    _REG_NOTIFY_CHANGE_NAME: Final = 0x00000001
    _REG_NOTIFY_CHANGE_LAST_SET: Final = 0x00000004
    _KEY_NOTIFY: Final = 0x0010
    _KEY_READ: Final = 0x20019
    _WAIT_OBJECT_0: Final = 0
    _WAIT_TIMEOUT: Final = 0x00000102
    _WAIT_FAILED: Final = 0xFFFFFFFF

    def __init__(self, install_parent: Path) -> None:
        """Arm directory and registry notifications before an NSIS state change."""
        if sys.platform != "win32":
            msg = "installed NSIS provenance verification requires Windows"
            raise FeatureUnavailableError(msg)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        find_first = windows_function(
            self._kernel32,
            "FindFirstChangeNotificationW",
            [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32],
            ctypes.c_void_p,
        )
        directory_handle = cast(
            "int | None",
            find_first(
                str(install_parent),
                1,
                self._FILE_NOTIFY_CHANGE_FILE_NAME | self._FILE_NOTIFY_CHANGE_DIR_NAME,
            ),
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if directory_handle is None or directory_handle == invalid_handle:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "FindFirstChangeNotificationW failed")
        self._directory_handle: int | None = directory_handle
        self._registry_key: int | None = None
        self._registry_event: int | None = None
        try:
            self._open_registry_event()
        except Exception:
            self.close()
            raise

    def _open_registry_event(self) -> None:
        create_event = windows_function(
            self._kernel32,
            "CreateEventW",
            [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p],
            ctypes.c_void_p,
        )
        event = cast("int | None", create_event(None, 0, 0, None))
        if not event:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "CreateEventW failed for NSIS registry")
        registry_key = ctypes.c_void_p()
        open_key = windows_function(
            self._advapi32,
            "RegOpenKeyExW",
            [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
            ],
            ctypes.c_long,
        )
        status = cast(
            "int",
            open_key(
                ctypes.c_void_p(0x80000001),
                UNINSTALL_REGISTRY_PARENT,
                0,
                self._KEY_READ | self._KEY_NOTIFY,
                ctypes.byref(registry_key),
            ),
        )
        if status != 0:
            self._close_handle(event)
            raise OSError(status, "RegOpenKeyExW failed for NSIS registry")
        self._registry_key = cast("int", registry_key.value)
        self._registry_event = event
        self._arm_registry_event()

    def _arm_registry_event(self) -> None:
        registry_key = self._registry_key
        registry_event = self._registry_event
        if registry_key is None or registry_event is None:
            msg = "NSIS registry watcher is already closed"
            raise RuntimeError(msg)
        notify = windows_function(
            self._advapi32,
            "RegNotifyChangeKeyValue",
            [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_int,
            ],
            ctypes.c_long,
        )
        status = cast(
            "int",
            notify(
                registry_key,
                0,
                self._REG_NOTIFY_CHANGE_NAME | self._REG_NOTIFY_CHANGE_LAST_SET,
                registry_event,
                1,
            ),
        )
        if status != 0:
            raise OSError(status, "RegNotifyChangeKeyValue failed")

    def wait_for_change(self, timeout_ms: int) -> bool:
        """Block for one registry or filesystem event and rearm that event source."""
        directory_handle = self._directory_handle
        registry_event = self._registry_event
        if directory_handle is None or registry_event is None:
            msg = "NSIS completion watcher is already closed"
            raise RuntimeError(msg)
        handles = (ctypes.c_void_p * 2)(directory_handle, registry_event)
        wait = windows_function(
            self._kernel32,
            "WaitForMultipleObjects",
            [
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_int,
                ctypes.c_uint32,
            ],
            ctypes.c_uint32,
        )
        result = cast("int", wait(2, handles, 0, timeout_ms))
        if result == self._WAIT_OBJECT_0:
            find_next = windows_function(
                self._kernel32,
                "FindNextChangeNotification",
                [ctypes.c_void_p],
                ctypes.c_int,
            )
            require_windows_success(
                find_next(directory_handle), "FindNextChangeNotification"
            )
            return True
        if result == self._WAIT_OBJECT_0 + 1:
            self._arm_registry_event()
            return True
        if result == self._WAIT_TIMEOUT:
            return False
        if result == self._WAIT_FAILED:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "WaitForMultipleObjects failed for NSIS state")
        msg = f"WaitForMultipleObjects returned unexpected result {result}"
        raise RuntimeError(msg)

    def _close_handle(self, handle: int) -> None:
        close_handle = windows_function(
            self._kernel32,
            "CloseHandle",
            [ctypes.c_void_p],
            ctypes.c_int,
        )
        require_windows_success(close_handle(handle), "CloseHandle")

    def close(self) -> None:
        """Close directory, registry-key, and event handles exactly once."""
        registry_key = self._registry_key
        self._registry_key = None
        if registry_key is not None:
            close_key = windows_function(
                self._advapi32,
                "RegCloseKey",
                [ctypes.c_void_p],
                ctypes.c_long,
            )
            status = cast("int", close_key(registry_key))
            if status != 0:
                raise OSError(status, "RegCloseKey failed for NSIS state watcher")
        registry_event = self._registry_event
        self._registry_event = None
        if registry_event is not None:
            self._close_handle(registry_event)
        directory_handle = self._directory_handle
        self._directory_handle = None
        if directory_handle is not None:
            close_change = windows_function(
                self._kernel32,
                "FindCloseChangeNotification",
                [ctypes.c_void_p],
                ctypes.c_int,
            )
            require_windows_success(
                close_change(directory_handle), "FindCloseChangeNotification"
            )


@final
class WindowsInstallationCompletionWatcherFactory:
    """Native factory used only by the installed-parity orchestration path."""

    def create(self, install_parent: Path) -> InstallCompletionWatcher:
        """Create one pre-armed watcher for fixed NSIS registry and directory state."""
        return WindowsInstallationCompletionWatcher(install_parent)


def current_user_install_parent() -> Path:
    """Return the current-user NSIS install parent used by this Tauri package."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        msg = "LOCALAPPDATA is required for current-user NSIS install verification"
        raise RuntimeError(msg)
    install_parent = Path(local_app_data).resolve()
    if not install_parent.is_dir():
        msg = "LOCALAPPDATA does not name an existing install parent directory"
        raise RuntimeError(msg)
    return install_parent


def wait_for_install_completion(
    registry: InstalledApplicationRegistry,
    changes: InstallCompletionWatcher,
    timeout_ms: int,
    *,
    clock_ms: Callable[[], int] | None = None,
) -> InstalledApplication:
    """Await the exact HKCU entry until its values and installed EXE are complete."""
    now = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)
    deadline = now() + timeout_ms
    last_incomplete_reason = "authoritative uninstall entry is absent"
    while True:
        try:
            installed = registry.installed_application()
        except FeatureUnavailableError:
            raise
        except RuntimeError as error:
            last_incomplete_reason = str(error)
        else:
            if installed is not None:
                return installed
        remaining_ms = deadline - now()
        if remaining_ms <= 0 or not changes.wait_for_change(remaining_ms):
            msg = (
                "NSIS exited without a complete authoritative HKCU installation: "
                f"{last_incomplete_reason}"
            )
            raise TimeoutError(msg)


def wait_for_uninstall_completion(
    installed: InstalledApplication,
    registry: InstalledApplicationRegistry,
    changes: InstallCompletionWatcher,
    timeout_ms: int,
    *,
    clock_ms: Callable[[], int] | None = None,
) -> None:
    """Await both uninstall registry removal and install-directory removal by events."""
    now = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)
    deadline = now() + timeout_ms
    while True:
        try:
            current = registry.installed_application()
        except FeatureUnavailableError:
            raise
        except RuntimeError:
            # The exact app and uninstaller were validated before launch. NSIS can
            # remove the EXE before deleting its registry key, so this is only a
            # post-launch transitional state, never a preflight/install allowance.
            current = installed
        directory_removed = not installed.install_location.exists()
        if current is None and directory_removed:
            return
        if current is not None and current != installed:
            msg = "uninstall registry entry changed to an unexpected installation"
            raise RuntimeError(msg)
        remaining_ms = deadline - now()
        if remaining_ms <= 0 or not changes.wait_for_change(remaining_ms):
            msg = "silent uninstall did not remove its directory and registry entry"
            raise TimeoutError(msg)


@final
class InstallerChain:
    """Strict native NSIS install/uninstall chain with injectable unit-test seams."""

    def __init__(
        self,
        installer: Path,
        timeout_seconds: int,
        registry: InstalledApplicationRegistry,
        executor: NativeCommandExecutor,
        watchers: InstallCompletionWatcherFactory,
    ) -> None:
        """Bind one current NSIS installer to authoritative state boundaries."""
        self.installer = installer
        self.timeout_seconds = timeout_seconds
        self.registry = registry
        self.executor = executor
        self.watchers = watchers
        self.installer_exit_code: int | None = None
        self.uninstaller_exit_code: int | None = None

    def preflight_clean_state(self) -> None:
        """Fail closed rather than overwrite a pre-existing installed application."""
        if self.registry.installed_application() is not None:
            msg = "the authoritative HKCU uninstall entry already names an app"
            raise RuntimeError(msg)

    def install(self) -> tuple[InstalledApplication, int]:
        """Run NSIS /S after arming evented completion state for its exact HKCU key."""
        watcher = self.watchers.create(current_user_install_parent())
        try:
            exit_code = self.executor.run(
                (str(self.installer), "/S"),
                timeout_seconds=self.timeout_seconds,
                cwd=self.installer.parent,
            )
            self.installer_exit_code = exit_code
            if exit_code != 0:
                msg = f"NSIS installer exited with code {exit_code}"
                raise RuntimeError(msg)
            installed = wait_for_install_completion(
                self.registry,
                watcher,
                self.timeout_seconds * 1000,
            )
            return installed, exit_code
        finally:
            watcher.close()

    def late_resolve_installation(self) -> InstalledApplication | None:
        """Event-wait for post-failure NSIS publication without touching prior state."""
        watcher = self.watchers.create(current_user_install_parent())
        try:
            return wait_for_install_completion(
                self.registry,
                watcher,
                self.timeout_seconds * 1000,
            )
        except TimeoutError:
            return None
        finally:
            watcher.close()

    def uninstall(self, installed: InstalledApplication) -> int:
        """Silently uninstall and await registry and directory completion events."""
        current = self.registry.installed_application()
        if current != installed:
            msg = "installed application changed before silent uninstall"
            raise RuntimeError(msg)
        watcher = self.watchers.create(installed.install_location.parent)
        try:
            exit_code = self.executor.run(
                (str(installed.uninstaller), "/S"),
                timeout_seconds=self.timeout_seconds,
                cwd=installed.uninstaller.parent,
            )
            self.uninstaller_exit_code = exit_code
            if exit_code != 0:
                msg = f"NSIS uninstaller exited with code {exit_code}"
                raise RuntimeError(msg)
            wait_for_uninstall_completion(
                installed,
                self.registry,
                watcher,
                self.timeout_seconds * 1000,
            )
            return exit_code
        finally:
            watcher.close()


def cleanup_prior_state(evidence_dir: Path) -> dict[str, object]:
    """Remove only harness-owned qa-state directories from prior runs."""
    removed: list[str] = []
    blocked: list[str] = []
    if evidence_dir.is_dir():
        for state in sorted(evidence_dir.glob("*/qa-state")):
            if state.is_dir():
                try:
                    shutil.rmtree(state)
                    removed.append(state.parent.name)
                except OSError:
                    blocked.append(state.parent.name)
    return {
        "removed_run_ids": removed,
        "removed_count": len(removed),
        "blocked_run_ids": blocked,
    }


def _install_event(
    events: list[dict[str, object]],
    check: str,
    status: ReceiptStatus,
    details: Mapping[str, object] | None = None,
) -> None:
    """Append one deterministic top-level installed-parity chain event."""
    events.append(
        {
            "sequence": len(events) + 1,
            "timestamp": utc_now(),
            "check": check,
            "status": status.value,
            "details": dict(details or {}),
        }
    )


def _install_receipt_outcome(events: Sequence[Mapping[str, object]]) -> str:
    """Return the strict installed-parity outcome for ordered chain events."""
    return (
        ReceiptStatus.FAILED.value
        if any(event.get("status") != ReceiptStatus.PASSED.value for event in events)
        else ReceiptStatus.PASSED.value
    )


@dataclass(frozen=True)
class InstalledChildProvenance:
    """The exact source and binary identity passed to every installed child."""

    installer: Path
    executable: Path
    installer_sha256: str
    executable_sha256: str
    qa_harness_sha256: str


@dataclass
class InstalledParityReceiptState:
    """Mutable installed-parity evidence accumulated before its final atomic receipt."""

    run_id: str
    run_dir: Path
    qa_harness_sha256: str
    installer: dict[str, object]
    cleanup: dict[str, object]
    events: list[dict[str, object]]
    children: list[dict[str, object]]
    installed_executable: dict[str, object] | None = None
    observed_ports: list[int] = field(default_factory=list)


def _write_install_receipt(state: InstalledParityReceiptState) -> dict[str, object]:
    """Atomically write the source-hash-bound installed parity receipt."""
    counts = {
        status.value: sum(event.get("status") == status.value for event in state.events)
        for status in (ReceiptStatus.FAILED, ReceiptStatus.PASSED)
    }
    receipt: dict[str, object] = {
        "schema_version": 1,
        "run_id": state.run_id,
        "scenario": INSTALLED_PARITY_SCENARIO,
        "qa_harness_sha256": state.qa_harness_sha256,
        "finished_at": utc_now(),
        "outcome": _install_receipt_outcome(state.events),
        "counts": counts,
        "installer": dict(state.installer),
        "installed_executable": dict(state.installed_executable or {}),
        "children": [dict(child) for child in state.children],
        "chain": [dict(event) for event in state.events],
        "cleanup": dict(state.cleanup),
    }
    path = state.run_dir / "install-receipt.json"
    temporary = path.with_suffix(".json.tmp")
    _ = temporary.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _ = temporary.replace(path)
    return receipt


def _assert_current_hash(path: Path, expected: str, label: str) -> None:
    """Reject an artifact that changed after its provenance hash was captured."""
    if sha256_file(path) != expected:
        msg = f"{label} hash changed after installed-parity preflight"
        raise RuntimeError(msg)


def installed_child_command(
    options: CliOptions,
    scenario: str,
    evidence_dir: Path,
    provenance: InstalledChildProvenance,
) -> list[str]:
    """Build the exact source-bound child invocation for one installed scenario."""
    return [
        sys.executable,
        str(HARNESS_SOURCE),
        "--scenario",
        scenario,
        "--exe",
        str(provenance.executable),
        "--installer",
        str(provenance.installer),
        "--evidence-dir",
        str(evidence_dir),
        "--run-id",
        "child",
        "--timeout-seconds",
        str(options.timeout_seconds),
        "--installed-child",
        "--qa-harness-sha256",
        provenance.qa_harness_sha256,
        "--expected-exe-sha256",
        provenance.executable_sha256,
        "--expected-installer-sha256",
        provenance.installer_sha256,
    ]


def _receipt_mapping(path: Path) -> dict[str, object]:
    """Read one child JSON receipt as a strict object mapping."""
    return require_mapping(
        cast("object", json.loads(path.read_text(encoding="utf-8"))),
        "child receipt",
    )


def _child_launch_event(events: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Return the unique source-bound child launch event."""
    launches = [
        event for event in events if event.get("check") == "launch-packaged-executable"
    ]
    if len(launches) != 1:
        msg = "child receipt did not contain exactly one launch event"
        raise RuntimeError(msg)
    return dict(launches[0])


def _verify_child_receipt(
    path: Path,
    scenario: str,
    provenance: InstalledChildProvenance,
) -> tuple[dict[str, object], list[int]]:
    """Verify a child receipt is source-bound to the resolved installed EXE."""
    receipt = _receipt_mapping(path)
    if (
        receipt.get("scenario") != scenario
        or receipt.get("qa_harness_sha256") != provenance.qa_harness_sha256
        or receipt.get("outcome") != ReceiptStatus.PASSED.value
    ):
        msg = "child receipt scenario, outcome, or harness source hash mismatched"
        raise RuntimeError(msg)
    counts = require_mapping(receipt.get("counts"), "child receipt counts")
    events = require_mapping_list(receipt.get("events"), "child receipt events")
    launch = _child_launch_event(events)
    if launch.get("status") != ReceiptStatus.PASSED.value:
        msg = "child launch event did not pass"
        raise RuntimeError(msg)
    details = require_mapping(launch.get("details"), "child launch details")
    if (
        details.get("qa_harness_sha256") != provenance.qa_harness_sha256
        or details.get("installer_sha256") != provenance.installer_sha256
        or details.get("executable_sha256") != provenance.executable_sha256
    ):
        msg = "child launch event was not bound to its expected installer and EXE"
        raise RuntimeError(msg)
    cleanup_events = [event for event in events if event.get("check") == "cleanup"]
    if (
        len(cleanup_events) != 1
        or cleanup_events[0].get("status") != ReceiptStatus.PASSED.value
    ):
        msg = "child receipt did not prove successful process cleanup"
        raise RuntimeError(msg)
    cleanup_details = require_mapping(
        cleanup_events[0].get("details"), "child cleanup details"
    )
    process = require_mapping(cleanup_details.get("process"), "child cleanup process")
    errors = process.get("errors")
    if errors != [] or process.get("devtools_port_closed") is not True:
        msg = "child cleanup did not close its process tree and DevTools port"
        raise RuntimeError(msg)
    ports: list[int] = []
    for event in events:
        event_details = require_mapping(event.get("details"), "child event details")
        port = event_details.get("devtools_port")
        if isinstance(port, int) and not isinstance(port, bool):
            ports.append(port)
    return {
        "outcome": receipt["outcome"],
        "counts": counts,
        "qa_harness_sha256": receipt["qa_harness_sha256"],
    }, ports


def _run_installed_child(
    options: CliOptions,
    run_dir: Path,
    scenario: str,
    provenance: InstalledChildProvenance,
) -> tuple[dict[str, object], list[int]]:
    """Run one child in a deterministic evidence path and verify its receipt chain."""
    evidence_dir = run_dir / "children" / scenario
    receipt_path = evidence_dir / "child" / "receipt.json"
    command = installed_child_command(options, scenario, evidence_dir, provenance)
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=str(HARNESS_SOURCE.parent),
        stdin=subprocess.DEVNULL,
        check=False,
        shell=False,
        timeout=options.timeout_seconds * 20,
    )
    result: dict[str, object] = {
        "scenario": scenario,
        "command": command,
        "exit_code": completed.returncode,
    }
    if not receipt_path.is_file():
        msg = "installed-parity child did not write its deterministic receipt path"
        raise RuntimeError(msg)
    receipt_details, ports = _verify_child_receipt(receipt_path, scenario, provenance)
    result.update(receipt_details)
    result["receipt_path"] = receipt_path.relative_to(run_dir).as_posix()
    result["receipt_sha256"] = sha256_file(receipt_path)
    if completed.returncode != 0:
        msg = f"installed-parity {scenario} child exited with {completed.returncode}"
        raise RuntimeError(msg)
    return result, ports


def _installed_child_provenance(
    installed: InstalledApplication,
    installer: Path,
    installer_sha256: str,
    qa_harness_sha256: str,
) -> tuple[InstalledChildProvenance, dict[str, object]]:
    """Hash the registry-resolved executable once before either child is launched."""
    executable_sha256 = sha256_file(installed.executable)
    provenance = InstalledChildProvenance(
        installer=installer,
        executable=installed.executable,
        installer_sha256=installer_sha256,
        executable_sha256=executable_sha256,
        qa_harness_sha256=qa_harness_sha256,
    )
    details: dict[str, object] = {
        "path": str(installed.executable),
        "bytes": installed.executable.stat().st_size,
        "sha256": executable_sha256,
        "install_location": str(installed.install_location),
        "registry_subkey": UNINSTALL_REGISTRY_SUBKEY,
    }
    return provenance, details


def _run_installed_children(
    options: CliOptions,
    state: InstalledParityReceiptState,
    provenance: InstalledChildProvenance,
) -> bool:
    """Run both required scenarios even if the first child receipt fails."""
    failed_scenarios: list[str] = []
    for scenario in INSTALLED_PARITY_CHILD_SCENARIOS:
        try:
            _assert_current_hash(
                provenance.installer, provenance.installer_sha256, "installer"
            )
            _assert_current_hash(
                HARNESS_SOURCE,
                provenance.qa_harness_sha256,
                "QA harness source",
            )
            child, ports = _run_installed_child(
                options, state.run_dir, scenario, provenance
            )
            state.children.append(child)
            state.observed_ports.extend(ports)
            _install_event(
                state.events,
                f"child-{scenario}",
                ReceiptStatus.PASSED,
                child,
            )
        except Exception as error:  # noqa: BLE001
            failed_scenarios.append(scenario)
            _install_event(
                state.events,
                f"child-{scenario}",
                ReceiptStatus.FAILED,
                {"error_type": type(error).__name__, "error": str(error)},
            )
    ports_closed = not any(loopback_port_is_open(port) for port in state.observed_ports)
    state.cleanup["process_cleanup"] = not failed_scenarios
    state.cleanup["devtools_ports"] = state.observed_ports
    state.cleanup["ports_closed"] = ports_closed
    if not ports_closed:
        _install_event(
            state.events,
            "child-devtools-port-cleanup",
            ReceiptStatus.FAILED,
            {"ports": state.observed_ports},
        )
    return not failed_scenarios and ports_closed


def _late_resolve_installation(
    chain: InstallerChain,
    state: InstalledParityReceiptState,
) -> InstalledApplication | None:
    """Recover a delayed post-install HKCU entry without touching pre-existing apps."""
    if chain.installer_exit_code is None:
        return None
    try:
        installed = chain.late_resolve_installation()
    except Exception as error:  # noqa: BLE001
        _install_event(
            state.events,
            "late-resolve-installed-state",
            ReceiptStatus.FAILED,
            {"error_type": type(error).__name__, "error": str(error)},
        )
        return None
    if installed is not None:
        state.cleanup["late_resolved"] = True
        _install_event(
            state.events,
            "late-resolve-installed-state",
            ReceiptStatus.PASSED,
            {"executable": str(installed.executable)},
        )
    return installed


def _record_uninstall_cleanup(
    chain: InstallerChain,
    installed: InstalledApplication | None,
    registry: InstalledApplicationRegistry,
    state: InstalledParityReceiptState,
) -> None:
    """Uninstall the known or late-resolved app and record all cleanup outcomes."""
    target = installed or _late_resolve_installation(chain, state)
    if target is None:
        _install_event(
            state.events,
            "silent-uninstall-evented-cleanup",
            ReceiptStatus.FAILED,
            {"error": "installer did not yield a validated installed app"},
        )
        return
    try:
        state.cleanup["uninstaller_command"] = [str(target.uninstaller), "/S"]
        state.cleanup["uninstall_registry_subkey"] = UNINSTALL_REGISTRY_SUBKEY
        state.cleanup["uninstaller_exit_code"] = chain.uninstall(target)
        state.cleanup["directory_removed"] = not target.install_location.exists()
        state.cleanup["registry_removed"] = registry.installed_application() is None
        status = (
            ReceiptStatus.PASSED
            if state.cleanup["directory_removed"] and state.cleanup["registry_removed"]
            else ReceiptStatus.FAILED
        )
        _install_event(
            state.events,
            "silent-uninstall-evented-cleanup",
            status,
            state.cleanup,
        )
    except Exception as error:  # noqa: BLE001
        _install_event(
            state.events,
            "silent-uninstall-evented-cleanup",
            ReceiptStatus.FAILED,
            {"error_type": type(error).__name__, "error": str(error)},
        )


def _captured_file_identity(
    details: Mapping[str, object], label: str
) -> tuple[int, str]:
    """Return a captured byte count and SHA-256 digest from receipt authority."""
    byte_count = require_int(details.get("bytes"), f"{label} bytes")
    sha256 = details.get("sha256")
    if not isinstance(sha256, str) or not SHA256_HEX.fullmatch(sha256):
        msg = f"{label} did not contain a SHA-256 digest"
        raise RuntimeError(msg)
    return byte_count, sha256


def _installed_children_by_scenario(
    state: InstalledParityReceiptState,
) -> dict[str, dict[str, object]]:
    """Return the exact two captured child entries, keyed by required scenario."""
    if len(state.children) != len(INSTALLED_PARITY_CHILD_SCENARIOS):
        msg = "installed-parity receipt did not capture both child scenarios"
        raise RuntimeError(msg)
    children: dict[str, dict[str, object]] = {}
    for child in state.children:
        scenario = child.get("scenario")
        if (
            not isinstance(scenario, str)
            or scenario not in INSTALLED_PARITY_CHILD_SCENARIOS
            or scenario in children
        ):
            msg = "installed-parity receipt captured an invalid child scenario"
            raise RuntimeError(msg)
        children[scenario] = child
    if set(children) != set(INSTALLED_PARITY_CHILD_SCENARIOS):
        msg = "installed-parity receipt did not capture every required child scenario"
        raise RuntimeError(msg)
    return children


def _post_chain_child_receipt_path(
    run_dir: Path,
    child: Mapping[str, object],
    scenario: str,
) -> Path:
    """Resolve a deterministic child receipt path only when its entry names it."""
    expected_path = Path("children", scenario, "child", "receipt.json").as_posix()
    if child.get("receipt_path") != expected_path:
        msg = "child receipt path did not match its deterministic top-level entry"
        raise RuntimeError(msg)
    return run_dir / expected_path


def _verify_post_chain_child(
    state: InstalledParityReceiptState,
    child: Mapping[str, object],
    scenario: str,
    installer_identity: tuple[int, str],
    executable_identity: tuple[int, str],
) -> dict[str, object]:
    """Revalidate one durable child receipt against captured top-level authority."""
    receipt_path = _post_chain_child_receipt_path(state.run_dir, child, scenario)
    receipt_sha256 = child.get("receipt_sha256")
    if not isinstance(receipt_sha256, str) or not SHA256_HEX.fullmatch(receipt_sha256):
        msg = "child receipt entry did not contain a SHA-256 digest"
        raise RuntimeError(msg)
    if not receipt_path.is_file():
        msg = f"child receipt is missing: {receipt_path}"
        raise RuntimeError(msg)
    actual_receipt_sha256 = sha256_file(receipt_path)
    if actual_receipt_sha256 != receipt_sha256:
        msg = "child receipt hash did not match its top-level entry"
        raise RuntimeError(msg)
    receipt = _receipt_mapping(receipt_path)
    receipt_counts = require_mapping(receipt.get("counts"), "child receipt counts")
    child_counts = require_mapping(child.get("counts"), "top-level child counts")
    if (
        child.get("scenario") != scenario
        or receipt.get("scenario") != scenario
        or receipt.get("outcome") != ReceiptStatus.PASSED.value
        or receipt.get("outcome") != child.get("outcome")
        or receipt_counts != child_counts
        or receipt.get("qa_harness_sha256") != state.qa_harness_sha256
        or receipt.get("qa_harness_sha256") != child.get("qa_harness_sha256")
    ):
        msg = "child receipt scenario, outcome, counts, or harness hash mismatched"
        raise RuntimeError(msg)
    events = require_mapping_list(receipt.get("events"), "child receipt events")
    launch = _child_launch_event(events)
    launch_details = require_mapping(launch.get("details"), "child launch details")
    installer_bytes, installer_sha256 = installer_identity
    executable_bytes, executable_sha256 = executable_identity
    expected_launch_details = {
        "qa_harness_sha256": state.qa_harness_sha256,
        "installer_bytes": installer_bytes,
        "installer_sha256": installer_sha256,
        "executable_bytes": executable_bytes,
        "executable_sha256": executable_sha256,
    }
    if launch.get("status") != ReceiptStatus.PASSED.value or any(
        launch_details.get(name) != value
        for name, value in expected_launch_details.items()
    ):
        msg = "child launch event did not match captured installer and EXE authority"
        raise RuntimeError(msg)
    return {
        "scenario": scenario,
        "receipt_sha256": actual_receipt_sha256,
        "outcome": receipt["outcome"],
        "counts": receipt_counts,
        "qa_harness_sha256": receipt["qa_harness_sha256"],
        "launch": expected_launch_details,
    }


def _post_chain_cleanup_flags(cleanup: Mapping[str, object]) -> dict[str, object]:
    """Require every top-level cleanup flag to remain explicitly true."""
    flags = {name: cleanup.get(name) for name in INSTALLED_PARITY_CLEANUP_FLAGS}
    failed_flags = [name for name, value in flags.items() if value is not True]
    if failed_flags:
        msg = "installed-parity cleanup flags were not all true: " + ", ".join(
            failed_flags
        )
        raise RuntimeError(msg)
    return flags


def _post_chain_integrity_details(
    state: InstalledParityReceiptState,
    installer: Path,
) -> dict[str, object]:
    """Revalidate every surviving installed-parity provenance boundary."""
    installer_bytes, installer_sha256 = _captured_file_identity(
        state.installer, "installer"
    )
    if installer.stat().st_size != installer_bytes:
        msg = "installer bytes changed after installed-parity preflight"
        raise RuntimeError(msg)
    _assert_current_hash(installer, installer_sha256, "installer")
    _assert_current_hash(HARNESS_SOURCE, state.qa_harness_sha256, "QA harness source")
    installed_executable = state.installed_executable
    if installed_executable is None:
        msg = "installed executable authority was not captured before cleanup"
        raise RuntimeError(msg)
    executable_identity = _captured_file_identity(
        installed_executable, "installed executable"
    )
    children = _installed_children_by_scenario(state)
    child_details = [
        _verify_post_chain_child(
            state,
            children[scenario],
            scenario,
            (installer_bytes, installer_sha256),
            executable_identity,
        )
        for scenario in INSTALLED_PARITY_CHILD_SCENARIOS
    ]
    cleanup_flags = _post_chain_cleanup_flags(state.cleanup)
    return {
        "installer": {"bytes": installer_bytes, "sha256": installer_sha256},
        "qa_harness_source": {
            "path": str(HARNESS_SOURCE),
            "sha256": state.qa_harness_sha256,
        },
        "children": child_details,
        "cleanup_flags": cleanup_flags,
    }


def record_post_chain_integrity(
    state: InstalledParityReceiptState,
    installer: Path,
) -> None:
    """Record the terminal installed-parity provenance revalidation."""
    try:
        details = _post_chain_integrity_details(state, installer)
    except Exception as error:  # noqa: BLE001
        _install_event(
            state.events,
            "post-chain-provenance-integrity",
            ReceiptStatus.FAILED,
            {"error_type": type(error).__name__, "error": str(error)},
        )
    else:
        _install_event(
            state.events,
            "post-chain-provenance-integrity",
            ReceiptStatus.PASSED,
            details,
        )


def _installed_parity_run_id(options: CliOptions) -> str:
    """Create the top-level evidence directory name unless callers supplied one."""
    generated = (
        f"install-{utc_now().replace(':', '').replace('.', '')}-{uuid4().hex[:8]}"
    )
    return options.run_id or generated


def run_installed_parity(options: CliOptions) -> int:
    """Install once, run both full scenarios against that exact EXE, then remove it."""
    installer = options.installer
    if installer is None:
        msg = "installed-parity requires a validated NSIS installer"
        raise AssertionError(msg)
    options.evidence_dir.mkdir(parents=True, exist_ok=True)
    run_id = _installed_parity_run_id(options)
    run_dir = options.evidence_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    installer_sha256 = sha256_file(installer)
    state = InstalledParityReceiptState(
        run_id=run_id,
        run_dir=run_dir,
        qa_harness_sha256=sha256_file(HARNESS_SOURCE),
        installer={
            "path": str(installer),
            "bytes": installer.stat().st_size,
            "sha256": installer_sha256,
            "command": [str(installer), "/S"],
            "exit_code": None,
        },
        cleanup={
            "uninstaller_exit_code": None,
            "directory_removed": False,
            "registry_removed": False,
            "process_cleanup": False,
            "ports_closed": False,
        },
        events=[],
        children=[],
    )
    registry = WindowsUninstallRegistry()
    chain = InstallerChain(
        installer,
        options.timeout_seconds,
        registry,
        WindowsNativeCommandExecutor(),
        WindowsInstallationCompletionWatcherFactory(),
    )
    installed: InstalledApplication | None = None
    try:
        chain.preflight_clean_state()
        _install_event(
            state.events, "preflight-clean-installed-state", ReceiptStatus.PASSED
        )
        _assert_current_hash(installer, installer_sha256, "installer")
        installed, installer_exit_code = chain.install()
        state.installer["exit_code"] = installer_exit_code
        _assert_current_hash(installer, installer_sha256, "installer")
        _assert_current_hash(
            HARNESS_SOURCE, state.qa_harness_sha256, "QA harness source"
        )
        provenance, state.installed_executable = _installed_child_provenance(
            installed,
            installer,
            installer_sha256,
            state.qa_harness_sha256,
        )
        _install_event(
            state.events,
            "install-exact-nsis-silent",
            ReceiptStatus.PASSED,
            {
                "command": [str(installer), "/S"],
                "exit_code": installer_exit_code,
                "installed_executable_sha256": provenance.executable_sha256,
                "installed_executable_bytes": installed.executable.stat().st_size,
            },
        )
        if not _run_installed_children(options, state, provenance):
            _install_event(
                state.events,
                "installed-parity-chain",
                ReceiptStatus.FAILED,
                {"error": "one or more installed child scenarios failed"},
            )
    except Exception as error:  # noqa: BLE001
        _install_event(
            state.events,
            "installed-parity-chain",
            ReceiptStatus.FAILED,
            {"error_type": type(error).__name__, "error": str(error)},
        )
    finally:
        _record_uninstall_cleanup(chain, installed, registry, state)
    state.installer["exit_code"] = chain.installer_exit_code
    state.cleanup["uninstaller_exit_code"] = chain.uninstaller_exit_code
    record_post_chain_integrity(state, installer)
    receipt = _write_install_receipt(state)
    print(run_dir)
    return 0 if receipt["outcome"] == ReceiptStatus.PASSED.value else 1


def run_main(options: CliOptions) -> int:
    """Execute validated options and map the receipt outcome to an exit code."""
    if options.scenario == INSTALLED_PARITY_SCENARIO:
        return run_installed_parity(options)
    options.evidence_dir.mkdir(parents=True, exist_ok=True)
    run_id = (
        options.run_id
        or f"{utc_now().replace(':', '').replace('.', '')}-{uuid4().hex[:8]}"
    )
    receipts = ReceiptStore(
        options.evidence_dir,
        ReceiptContext(
            scenario=options.scenario,
            run_id=run_id,
            secrets=environment_secrets(),
            expected_qa_harness_sha256=options.qa_harness_sha256,
        ),
    )
    if options.cleanup_only:
        cleanup = cleanup_prior_state(options.evidence_dir)
        status = (
            ReceiptStatus.FAILED if cleanup["blocked_run_ids"] else ReceiptStatus.PASSED
        )
        _ = receipts.record("cleanup-prior-state", status, cleanup)
        summary = receipts.finish()
        print(receipts.run_dir)
        return 0 if summary["outcome"] == ReceiptStatus.PASSED.value else 1

    runner = QaRunner(options, receipts)
    try:
        runner.run()
    finally:
        try:
            cleanup = runner.cleanup()
            cleanup_status = (
                ReceiptStatus.PASSED
                if options.keep_qa_data or cleanup["removed"] is True
                else ReceiptStatus.FAILED
            )
            _ = receipts.record("cleanup", cleanup_status, cleanup)
        except Exception as error:  # noqa: BLE001  # pragma: no cover
            # Cleanup failures must become receipts rather than masking the run.
            _ = receipts.record(
                "cleanup",
                ReceiptStatus.FAILED,
                {"error_type": type(error).__name__, "error": str(error)},
            )
    summary = receipts.finish()
    print(receipts.run_dir)
    outcome = summary["outcome"]
    if outcome == ReceiptStatus.PASSED.value:
        return 0
    if outcome == ReceiptStatus.UNAVAILABLE.value:
        return 3
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    return run_main(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
