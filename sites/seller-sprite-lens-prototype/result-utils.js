function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function objectRowsToSheet(rows, name = "查询结果") {
  const columns = [];
  for (const row of rows) {
    if (!isRecord(row)) continue;
    for (const key of Object.keys(row)) if (!columns.includes(key)) columns.push(key);
  }
  if (!columns.length) {
    return { name, columns: ["value"], rows: rows.map((value) => [value]), numberFormats: [null] };
  }
  return {
    name,
    columns,
    rows: rows.map((row) => columns.map((column) => isRecord(row) ? row[column] : undefined)),
    numberFormats: columns.map(() => null),
  };
}

function workbookSheet(value, fallbackName) {
  return {
    name: String(value.name || value.sheet_name || fallbackName),
    columns: Array.isArray(value.columns) ? value.columns.map(String) : [],
    rows: Array.isArray(value.rows) ? value.rows : [],
    numberFormats: Array.isArray(value.number_formats) ? value.number_formats : [],
  };
}

export function resultSheets(value) {
  if (isRecord(value) && Array.isArray(value.columns) && Array.isArray(value.rows)) {
    const sheets = [workbookSheet(value, "查询结果")];
    for (const sheet of value.additional_sheets || []) {
      if (isRecord(sheet) && Array.isArray(sheet.columns) && Array.isArray(sheet.rows)) {
        sheets.push(workbookSheet(sheet, `工作表 ${sheets.length + 1}`));
      }
    }
    return sheets;
  }
  if (Array.isArray(value)) return [objectRowsToSheet(value)];
  if (isRecord(value)) {
    for (const key of ["result", "data", "items", "results"]) {
      if (Array.isArray(value[key]) || isRecord(value[key])) {
        const nested = resultSheets(value[key]);
        if (nested.length) return nested;
      }
    }
    return [objectRowsToSheet([value])];
  }
  if (value === undefined) return [];
  return [objectRowsToSheet([value])];
}

export function displayValue(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function visibleMatrixRows(sheet, filter = "", sortIndex = -1, sortDirection = 1) {
  const query = String(filter || "").trim().toLocaleLowerCase("zh-CN");
  const rows = sheet.rows.map((row, index) => ({ row, index }));
  const filtered = query
    ? rows.filter(({ row }) => row.some((value) => displayValue(value).toLocaleLowerCase("zh-CN").includes(query)))
    : rows;
  if (sortIndex < 0) return filtered;
  return filtered.toSorted((left, right) => {
    const a = left.row[sortIndex];
    const b = right.row[sortIndex];
    if (typeof a === "number" && typeof b === "number") return (a - b) * sortDirection;
    return displayValue(a).localeCompare(displayValue(b), "zh-CN", { numeric: true }) * sortDirection;
  });
}

function csvCell(value) {
  let text = displayValue(value);
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function matrixCsv(sheet, rows = sheet.rows) {
  const lines = [sheet.columns.map(csvCell).join(",")];
  for (const row of rows) lines.push(sheet.columns.map((_, index) => csvCell(row[index])).join(","));
  return `\uFEFF${lines.join("\r\n")}`;
}

export function formatMatrixValue(value, numberFormat) {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "number" && typeof numberFormat === "string") {
    if (numberFormat.includes("%")) {
      return new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 2 }).format(value);
    }
    if (numberFormat.includes("#,##0")) {
      const decimals = numberFormat.includes(".00") ? 2 : 0;
      return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value);
    }
  }
  return displayValue(value);
}
