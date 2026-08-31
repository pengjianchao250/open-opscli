export function tableKeys(rows, primitiveKey = "value") {
  const firstValue = rows.find((row) => row !== undefined && row !== null);
  if (firstValue !== undefined && firstValue !== null && (typeof firstValue !== "object" || Array.isArray(firstValue))) return [primitiveKey];
  const keys = [];
  for (const row of rows) {
    if (!row || typeof row !== "object" || Array.isArray(row)) continue;
    for (const key of Object.keys(row)) if (!keys.includes(key)) keys.push(key);
  }
  return keys.length || !rows.length ? keys : [primitiveKey];
}

export function tableValue(row, key, primitiveKey = "value") {
  if (row && typeof row === "object" && !Array.isArray(row)) return row[key];
  return key === primitiveKey ? row : undefined;
}

export function visibleTableRows(rows, filter, sortKey, sortDir, primitiveKey = "value") {
  const needle = String(filter || "").toLowerCase();
  const visibleRows = rows
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => !needle || JSON.stringify(row).toLowerCase().includes(needle));

  if (sortKey) {
    visibleRows.sort((a, b) => {
      const left = tableValue(a.row, sortKey, primitiveKey);
      const right = tableValue(b.row, sortKey, primitiveKey);
      return String(left ?? "").localeCompare(String(right ?? ""), undefined, { numeric: true }) * sortDir;
    });
  }
  return visibleRows;
}

function csvValue(value) {
  if (value === null || value === undefined) return "";
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  const safeText = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safeText.replaceAll('"', '""')}"`;
}

export function tableCsv(rows, keys = tableKeys(rows), primitiveKey = "value") {
  const lines = [keys.map(csvValue).join(",")];
  for (const row of rows) lines.push(keys.map((key) => csvValue(tableValue(row, key, primitiveKey))).join(","));
  return `\uFEFF${lines.join("\r\n")}`;
}
