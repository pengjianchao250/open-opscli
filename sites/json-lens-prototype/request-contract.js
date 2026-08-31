export function normalizeApiKey(apiKey) {
  return String(apiKey || "")
    .trim()
    .replace(/^authorization\s*:\s*/i, "")
    .replace(/^bearer\s+/i, "")
    .trim();
}

export function buildRequestHeaders(apiKey) {
  const headers = { "Content-Type": "application/json" };
  const token = normalizeApiKey(apiKey);
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}
