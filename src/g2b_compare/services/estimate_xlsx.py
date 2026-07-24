"""Targeted OOXML edits that preserve unsupported legacy drawings."""

from __future__ import annotations

import io
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, cast
from xml.etree import ElementTree as ET

from .estimate_export_models import EstimateExportError

if TYPE_CHECKING:
    from decimal import Decimal
    from xml.etree.ElementTree import Element

    from .estimate_export_models import ComparisonSnapshot, TemplateManifest
    from .estimate_models import EstimateDraft, EstimateLine

SHEET_NS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS: Final = "http://www.w3.org/XML/1998/namespace"
NO_SHEET_DATA: Final = "워크시트 데이터가 없음"


def write_draft(
    entries: dict[str, bytes],
    manifest: TemplateManifest,
    draft: EstimateDraft,
    comparisons: dict[str, tuple[ComparisonSnapshot, ...]],
) -> None:
    """Update only mapped workbook cells and calculation flags."""
    sheet_paths = _sheet_paths(entries)
    title_sheet = manifest.title_cell["sheet"]
    title_root = _trusted_xml(entries[sheet_paths[title_sheet]])
    _set_cell(title_root, manifest.title_cell["cell"], draft.title)
    entries[sheet_paths[title_sheet]] = _xml(title_root)

    quantity_sheet = str(manifest.quantity_rows["sheet"])
    quantity_root = _trusted_xml(entries[sheet_paths[quantity_sheet]])
    quantity_start = int(manifest.quantity_rows["start_row"])
    price_sheet = str(manifest.price_rows["sheet"])
    price_root = _trusted_xml(entries[sheet_paths[price_sheet]])
    price_start = int(manifest.price_rows["start_row"])
    for index in range(9):
        line = draft.lines[index] if index < len(draft.lines) else None
        _write_quantity_row(quantity_root, quantity_start + index, index, line)
        values = () if line is None else comparisons[line.id]
        _write_price_row(price_root, price_start + index, values)
    entries[sheet_paths[quantity_sheet]] = _xml(quantity_root)
    entries[sheet_paths[price_sheet]] = _xml(price_root)

    workbook = _trusted_xml(entries["xl/workbook.xml"])
    calc = workbook.find(f"{{{SHEET_NS}}}calcPr")
    if calc is None:
        calc = ET.SubElement(workbook, f"{{{SHEET_NS}}}calcPr")
    calc.set("calcMode", "auto")
    calc.set("fullCalcOnLoad", "1")
    calc.set("forceFullCalc", "1")
    entries["xl/workbook.xml"] = _xml(workbook)


def _write_quantity_row(
    root: Element,
    row: int,
    index: int,
    line: EstimateLine | None,
) -> None:
    for column in ("A", "B", "C", "D", "F", "G", "H", "I", "K"):
        _set_cell(root, f"{column}{row}", None)
    if line is None:
        return
    values: dict[str, str | Decimal] = {
        "A": f"1-{index + 1}",
        "B": line.item_name_snapshot,
        "C": line.spec_snapshot,
        "D": line.unit_snapshot,
        "F": line.quantity,
        "K": "본품" if line.line_kind == "main" else f"{line.parent_product_id} 옵션",
    }
    for column, value in values.items():
        _set_cell(root, f"{column}{row}", value)


def _write_price_row(
    root: Element,
    row: int,
    comparisons: tuple[ComparisonSnapshot, ...],
) -> None:
    columns = "FGHIJKLMNOPQ"
    for column in columns:
        _set_cell(root, f"{column}{row}", None)
    starts = {"A": "F", "B": "J", "C": "N"}
    for item in comparisons:
        offset = columns.index(starts[item.slot])
        values = (item.company, item.spec, item.product_id, item.price_won)
        for column, value in zip(columns[offset : offset + 4], values, strict=True):
            _set_cell(root, f"{column}{row}", value)


def _sheet_paths(entries: dict[str, bytes]) -> dict[str, str]:
    relationships = _trusted_xml(entries["xl/_rels/workbook.xml.rels"])
    targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
    workbook = _trusted_xml(entries["xl/workbook.xml"])
    result: dict[str, str] = {}
    sheets = workbook.findall(f"{{{SHEET_NS}}}sheets/{{{SHEET_NS}}}sheet")
    for sheet in sheets:
        relation_id = sheet.attrib[f"{{{REL_NS}}}id"]
        target = targets[relation_id].lstrip("/")
        result[sheet.attrib["name"]] = str(
            PurePosixPath("xl") / target.removeprefix("xl/")
        )
    return result


def _set_cell(root: Element, reference: str, value: str | int | Decimal | None) -> None:
    row_number = int(
        "".join(character for character in reference if character.isdigit())
    )
    sheet_data = root.find(f"{{{SHEET_NS}}}sheetData")
    if sheet_data is None:
        raise EstimateExportError(NO_SHEET_DATA)
    row = sheet_data.find(f"{{{SHEET_NS}}}row[@r='{row_number}']")
    if row is None:
        row = ET.SubElement(sheet_data, f"{{{SHEET_NS}}}row", {"r": str(row_number)})
    cell = row.find(f"{{{SHEET_NS}}}c[@r='{reference}']")
    if cell is None:
        cell = ET.SubElement(row, f"{{{SHEET_NS}}}c", {"r": reference})
    for child in list(cell):
        if child.tag.rsplit("}", 1)[-1] in {"f", "v", "is"}:
            cell.remove(child)
    _ = cell.attrib.pop("t", None)
    if value is None:
        return
    if isinstance(value, str):
        cell.set("t", "inlineStr")
        inline = ET.SubElement(cell, f"{{{SHEET_NS}}}is")
        text = ET.SubElement(inline, f"{{{SHEET_NS}}}t")
        text.set(f"{{{XML_NS}}}space", "preserve")
        text.text = value
    else:
        node = ET.SubElement(cell, f"{{{SHEET_NS}}}v")
        node.text = str(value)


def _trusted_xml(data: bytes) -> Element:
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        ET.register_namespace(prefix, uri)
    return ET.fromstring(data)  # noqa: S314 - immutable bundled workbook only


def _xml(root: Element) -> bytes:
    ET.register_namespace("", SHEET_NS)
    ET.register_namespace("r", REL_NS)
    return cast(
        "bytes",
        ET.tostring(root, encoding="utf-8", xml_declaration=True),
    )
