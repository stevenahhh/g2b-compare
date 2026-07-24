from pathlib import Path

import pytest

from g2b_compare.observability.secrets import verify_secrets


def test_secret_scan_ignores_tracked_path_missing_before_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: Git still reports a tracked path that was already deleted.
    missing = tmp_path / "removed.env"

    def missing_tracked_file(_root: Path) -> tuple[Path, ...]:
        return (missing,)

    monkeypatch.setattr(
        "g2b_compare.observability.secrets.tracked_files",
        missing_tracked_file,
    )

    # When: tracked source storage is scanned.
    leaks = verify_secrets(tmp_path)

    # Then: the absent path is not treated as a storage read failure.
    assert leaks == ()
