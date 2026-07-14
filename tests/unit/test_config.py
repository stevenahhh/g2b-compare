from __future__ import annotations

import hashlib
import ipaddress
from pathlib import Path

import pytest
from pydantic import ValidationError

from g2b_compare.config import (
    G2B_API_BASE_URL,
    AppSettings,
    ProductionBase,
    SyncSettings,
)
from g2b_compare.errors import (
    SourceArtifactError,
    SourceBaselineError,
    SourceCountError,
)
from g2b_compare.paths import validate_source_inventory

PUBLIC_BIND = str(ipaddress.IPv4Address(0))


def test_app_settings_do_not_require_sync_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: no service key in the process environment
    monkeypatch.delenv("G2B_SERVICE_KEY", raising=False)

    # When: local-only settings are created
    settings = AppSettings()

    # Then: the loopback default is available without a secret
    assert settings.bind_host == "127.0.0.1"
    assert settings.bind_port == 8765


def test_sync_settings_require_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: no service key in the process environment
    monkeypatch.delenv("G2B_SERVICE_KEY", raising=False)

    # When/Then: sync settings reject the missing secret
    with pytest.raises(ValidationError, match="service_key"):
        SyncSettings()


def test_sync_settings_redact_service_key() -> None:
    # Given: a distinctive service key
    secret = bytes.fromhex(
        "6e657665722d7072696e742d746869732d736572766963652d6b6579"
    ).decode()

    # When: sync settings are represented
    rendered = (
        f"{SyncSettings(service_key=secret)!r} {SyncSettings(service_key=secret)}"
    )

    # Then: the secret bytes never appear
    assert secret not in rendered


@pytest.mark.parametrize("host", [PUBLIC_BIND, "localhost", "192.0.2.10"])
def test_app_settings_reject_non_loopback_bind(host: str) -> None:
    # Given: a non-approved bind host
    # When/Then: the boundary rejects public or arbitrary hosts
    with pytest.raises(ValidationError, match=r"127\.0\.0\.1"):
        AppSettings(bind_host=host)


def test_app_settings_reject_invalid_daily_budget() -> None:
    # Given: a non-positive daily request budget
    # When/Then: configuration parsing rejects it
    with pytest.raises(ValidationError, match="daily_api_budget"):
        AppSettings(daily_api_budget=0)


def test_production_base_is_official_https_only() -> None:
    # Given: the immutable official service base
    # When: it is parsed at the configuration boundary
    base = ProductionBase(url=G2B_API_BASE_URL)

    # Then: the official HTTPS host and path are retained
    assert str(base.url).rstrip("/") == G2B_API_BASE_URL


@pytest.mark.parametrize(
    "url",
    [
        "http://apis.data.go.kr/1230000/ShoppingMallPrdctInfoService",
        "https://example.invalid/1230000/ShoppingMallPrdctInfoService",
    ],
)
def test_production_base_rejects_override(url: str) -> None:
    # Given: a non-official or non-HTTPS base
    # When/Then: production base parsing rejects the override
    with pytest.raises(ValidationError, match="official HTTPS"):
        ProductionBase(url=url)


def test_source_inventory_validates_four_declared_hashes(tmp_path: Path) -> None:
    # Given: four immutable source files and their declared hashes
    paths = tuple(Path(f"source-{index}.bin") for index in range(4))
    lines: list[str] = []
    for index, relative in enumerate(paths):
        payload = f"payload-{index}".encode()
        (tmp_path / relative).write_bytes(payload)
        lines.append(f"{hashlib.sha256(payload).hexdigest()}  {relative.as_posix()}")
    (tmp_path / "baseline.sha256").write_text("\n".join(lines), encoding="utf-8")

    # When: the inventory boundary validates the package
    inventory = validate_source_inventory(tmp_path, paths, Path("baseline.sha256"))

    # Then: all four verified files are reported
    assert inventory.count == 4


def test_source_inventory_rejects_missing_artifact(tmp_path: Path) -> None:
    # Given: a four-file declaration with no matching files
    paths = tuple(Path(f"source-{index}.bin") for index in range(4))
    (tmp_path / "baseline.sha256").write_text("", encoding="utf-8")

    # When/Then: the first missing source is reported
    with pytest.raises(SourceArtifactError, match=r"source artifact.*missing"):
        validate_source_inventory(tmp_path, paths, Path("baseline.sha256"))


def test_source_inventory_rejects_missing_baseline(tmp_path: Path) -> None:
    # Given: four files but no hash baseline
    paths = tuple(Path(f"source-{index}.bin") for index in range(4))
    for relative in paths:
        (tmp_path / relative).write_bytes(b"source")

    # When/Then: the absent baseline is reported
    with pytest.raises(SourceBaselineError, match=r"hash baseline.*missing"):
        validate_source_inventory(tmp_path, paths, Path("baseline.sha256"))


def test_source_inventory_rejects_unexpected_count(tmp_path: Path) -> None:
    # Given: only three declared source paths
    paths = tuple(Path(f"source-{index}.bin") for index in range(3))

    # When/Then: the invariant of four sources is enforced
    with pytest.raises(SourceCountError, match="expected 4 source artifacts"):
        validate_source_inventory(tmp_path, paths, Path("baseline.sha256"))
