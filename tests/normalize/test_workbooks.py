"""Given untrusted workbooks, verify fail-closed package inspection."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from g2b_compare.normalize import WorkbookExternalLinkError, inspect_workbook

if TYPE_CHECKING:
    from collections.abc import Callable

_WORKBOOK_RELATIONSHIPS = "xl/_rels/workbook.xml.rels"
_EXTERNAL_LINK_RELATION = (
    b'<Relationship Id="rIdExternal" '
    b'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    b'relationships/externalLink" Target="externalLink.xml"/>'
)


def _write_safe_workbook(path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet["A1"] = "safe"
    workbook.save(path)
    workbook.close()


def _add_external_link_entry(path: Path) -> None:
    external_link_xml = b"".join(
        (
            b'<externalLink xmlns="http://schemas.openxmlformats.org/',
            b'spreadsheetml/2006/main"/>',
        ),
    )
    with ZipFile(path, mode="a", compression=ZIP_DEFLATED) as package:
        package.writestr(
            "xl/externalLinks/externalLink1.xml",
            external_link_xml,
        )


def _add_external_link_relation(path: Path) -> None:
    with ZipFile(path) as package:
        entries = {name: package.read(name) for name in package.namelist()}
    relationships = entries[_WORKBOOK_RELATIONSHIPS]
    entries[_WORKBOOK_RELATIONSHIPS] = relationships.replace(
        b"</Relationships>",
        _EXTERNAL_LINK_RELATION + b"</Relationships>",
    )
    with ZipFile(path, mode="w", compression=ZIP_DEFLATED) as package:
        for name, content in entries.items():
            package.writestr(name, content)


@pytest.mark.parametrize(
    "craft_external_link",
    [_add_external_link_entry, _add_external_link_relation],
    ids=["external-link-entry", "external-link-relation"],
)
def test_inspection_rejects_package_only_external_link(
    tmp_path: Path,
    craft_external_link: Callable[[Path], None],
) -> None:
    # Given
    path = tmp_path / "package-only-external-link.xlsx"
    _write_safe_workbook(path)
    craft_external_link(path)

    # When
    with pytest.raises(WorkbookExternalLinkError) as captured:
        inspect_workbook(path)

    # Then
    assert captured.value.path == path


def test_exported_workbook_api_imports_without_dev_dependencies() -> None:
    # Given
    source = Path(__file__).resolve().parents[2] / "src"
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(source)!r}); "
        "from g2b_compare.normalize import ("
        "WorkbookExternalLinkError, inspect_workbook); "
        "assert callable(inspect_workbook); "
        "assert issubclass(WorkbookExternalLinkError, Exception); "
        "assert 'openpyxl' not in sys.modules; "
        "print('ok')"
    )

    # When
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-S", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "ok\n"
