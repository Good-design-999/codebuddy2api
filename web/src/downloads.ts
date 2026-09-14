function safeFilename(value: string | null | undefined): string | null {
  if (
    !value ||
    value.length > 255 ||
    Array.from(value).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
  )
    return null;
  const name = value.trim();
  return name && !/^\.+$/.test(name) && !/[\\/:*?"<>|]/.test(name) ? name : null;
}

/** Prefer UTF-8 filename* and fall back to a safe legacy name or the caller's default. */
export function downloadFilename(header: string, fallback: string): string {
  if (header.length > 8192 || header.includes("\r") || header.includes("\n")) return fallback;
  const parameters = new Map<string, string | null>();
  // Consume all parameters so quoted semicolons cannot introduce a fake filename.
  const pattern = /(?:^|;)\s*([^;=\s]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"\s*|([^";\s][^";]*))(?=;|$)/g;
  for (const match of header.matchAll(pattern)) {
    const key = match[1]!.toLowerCase();
    if (key !== "filename" && key !== "filename*") continue;
    const value = match[2] === undefined ? match[3]!.trim() : match[2].replace(/\\(.)/g, "$1");
    parameters.set(key, parameters.has(key) ? null : value);
  }
  const extended = parameters.get("filename*");
  const encoded = extended && /^utf-8'[^']*'(.*)$/i.exec(extended);
  if (encoded) {
    try {
      const name = safeFilename(decodeURIComponent(encoded[1]!));
      if (name) return name;
    } catch {
      // Invalid percent escapes or UTF-8 fall back to the legacy parameter.
    }
  }
  return safeFilename(parameters.get("filename")) ?? fallback;
}
