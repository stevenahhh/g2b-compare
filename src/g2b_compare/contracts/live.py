"""Durable entry point for the six-operation live contract capture."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Final, override

import httpx
from pydantic import ValidationError

from g2b_compare.contracts.capture import (
    CaptureBlockedError,
    CaptureContext,
    capture_all,
)
from g2b_compare.contracts.live_output import publish_blocker, publish_success
from g2b_compare.contracts.quota import QuotaManifest
from g2b_compare.contracts.wire import HttpxRequester, Requester
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.migrate import migrate

DEFAULT_LEDGER: Final = Path("var/contract-capture.sqlite3")
DEFAULT_QUOTA: Final = Path("docs/account-quota-observed.json")
DEFAULT_ROOT: Final = Path()
SOURCE_UNREADABLE: Final = "secret-source-unreadable"
KEY_NOT_UNIQUE: Final = "service-key-not-unique"
CLI_OPTIONS: Final = frozenset(
    {"--secret-source", "--ledger", "--quota", "--output-root"}
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class LiveCaptureConfig:
    """Filesystem and observation inputs for one durable invocation."""

    output_root: Path
    ledger_path: Path
    quota_path: Path
    secret_source: Path
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class LiveCaptureResult:
    """Sanitized outcome suitable for CLI status handling."""

    success: bool
    published: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class SecretSourceError(Exception):
    """Secret source omitted exactly one usable ServiceKey value."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


class _ServiceKeyParser(HTMLParser):
    """Extract only the value of the input identified as ServiceKey."""

    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    @override
    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "input":
            return
        attributes = dict(attrs)
        if attributes.get("id") == "ServiceKey" and attributes.get("value"):
            value = attributes["value"]
            if value is not None:
                self.values.append(value)


def load_service_key(path: Path) -> str:
    """Read one ServiceKey input value without exporting it from memory."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        raise SecretSourceError(SOURCE_UNREADABLE) from None
    parser = _ServiceKeyParser()
    parser.feed(source)
    if len(parser.values) != 1:
        raise SecretSourceError(KEY_NOT_UNIQUE)
    return parser.values[0]


def run_live_capture(
    config: LiveCaptureConfig,
    requester: Requester | None = None,
) -> LiveCaptureResult:
    """Run against a persistent ledger and publish only complete evidence."""
    try:
        secret = load_service_key(config.secret_source)
        quota = QuotaManifest.model_validate_json(config.quota_path.read_bytes())
    except SecretSourceError as error:
        blocker = publish_blocker(
            config.output_root, CaptureBlockedError("all", error.reason, 0)
        )
        return LiveCaptureResult(success=False, published=(blocker,))
    except OSError:
        blocker = publish_blocker(
            config.output_root, CaptureBlockedError("all", "quota-unreadable", 0)
        )
        return LiveCaptureResult(success=False, published=(blocker,))
    except ValidationError:
        blocker = publish_blocker(
            config.output_root, CaptureBlockedError("all", "quota-invalid", 0)
        )
        return LiveCaptureResult(success=False, published=(blocker,))
    config.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(config.ledger_path)
    repository = IngestRepository(config.ledger_path)
    if requester is not None:
        return _capture_with_requester(config, requester, repository, secret, quota)
    timeout = httpx.Timeout(connect=5, read=30, write=10, pool=10)
    with httpx.Client(
        follow_redirects=False,
        trust_env=False,
        timeout=timeout,
    ) as client:
        return _capture_with_requester(
            config, HttpxRequester(client), repository, secret, quota
        )


def _capture_with_requester(
    config: LiveCaptureConfig,
    requester: Requester,
    repository: IngestRepository,
    secret: str,
    quota: QuotaManifest,
) -> LiveCaptureResult:
    context = CaptureContext(
        requester=requester,
        repository=repository,
        service_key=secret,
        observed_at=config.observed_at,
    )
    try:
        captures = capture_all(context, quota)
    except CaptureBlockedError as error:
        blocker = publish_blocker(config.output_root, error)
        return LiveCaptureResult(success=False, published=(blocker,))
    published = publish_success(config.output_root, captures, secret)
    return LiveCaptureResult(success=True, published=published)


def parse_cli(argv: Sequence[str]) -> LiveCaptureConfig | None:
    """Parse only path-valued options without ever echoing rejected argv."""
    if len(argv) % 2 != 0:
        return None
    values: dict[str, str] = {}
    for index in range(0, len(argv), 2):
        option = argv[index]
        value = argv[index + 1]
        if option not in CLI_OPTIONS or option in values or value.startswith("--"):
            return None
        values[option] = value
    secret_source = values.get("--secret-source")
    if secret_source is None:
        return None
    return LiveCaptureConfig(
        output_root=Path(values.get("--output-root", DEFAULT_ROOT)),
        ledger_path=Path(values.get("--ledger", DEFAULT_LEDGER)),
        quota_path=Path(values.get("--quota", DEFAULT_QUOTA)),
        secret_source=Path(secret_source),
        observed_at=datetime.now(UTC),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Return a sanitized process status for the shipped capture command."""
    args = tuple(sys.argv[1:] if argv is None else argv)
    config = parse_cli(args)
    if config is None:
        _ = sys.stderr.write("invalid capture arguments\n")
        return 2
    result = run_live_capture(config)
    message = (
        "contract capture verified\n"
        if result.success
        else "contract capture blocked\n"
    )
    _ = sys.stdout.write(message)
    return 0 if result.success else 1
