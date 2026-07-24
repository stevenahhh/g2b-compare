import type ExcelJS from "exceljs";

const HEADER_FILL = "0F62FE";
const TITLE_FILL = "161616";

export function addTitle(
  sheet: ExcelJS.Worksheet,
  title: string,
  finalColumn: number
): void {
  sheet.mergeCells(1, 1, 1, finalColumn);
  const cell = sheet.getCell(1, 1);
  cell.value = title;
  cell.font = { bold: true, color: { argb: "FFFFFFFF" }, size: 14 };
  cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: `FF${TITLE_FILL}` } };
  cell.alignment = { vertical: "middle", horizontal: "left" };
  sheet.getRow(1).height = 26;
}

export function styleHeader(
  sheet: ExcelJS.Worksheet,
  rowNumber: number,
  headers: readonly string[]
): void {
  const row = sheet.getRow(rowNumber);
  row.values = [...headers];
  row.eachCell((cell) => {
    cell.font = { bold: true, color: { argb: "FFFFFFFF" } };
    cell.fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: `FF${HEADER_FILL}` }
    };
    cell.alignment = { vertical: "middle", horizontal: "center", wrapText: true };
    cell.border = {
      bottom: { style: "thin", color: { argb: "FF525252" } }
    };
  });
  row.height = 30;
}

export function finalizeTable(
  sheet: ExcelJS.Worksheet,
  headerRow: number,
  finalRow: number,
  finalColumn: number
): void {
  sheet.views = [{ state: "frozen", ySplit: headerRow }];
  sheet.autoFilter = {
    from: { row: headerRow, column: 1 },
    to: { row: finalRow, column: finalColumn }
  };
  sheet.getRows(headerRow + 1, finalRow - headerRow)?.forEach((row) => {
    row.eachCell({ includeEmpty: true }, (cell) => {
      cell.alignment = { vertical: "middle", wrapText: true };
      cell.border = {
        bottom: { style: "hair", color: { argb: "FFD9D9D9" } }
      };
    });
  });
}

export function setWidths(
  sheet: ExcelJS.Worksheet,
  widths: readonly number[]
): void {
  widths.forEach((width, index) => {
    sheet.getColumn(index + 1).width = width;
  });
}

