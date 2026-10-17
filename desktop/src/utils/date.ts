/**
 * Safely parse a date string from backend (which is in UTC, but may lack a trailing 'Z')
 * and return a local Date object in the user's browser timezone.
 */
export function parseUtcDate(dateStr?: string | null | number): Date | null {
  if (!dateStr) return null;
  if (typeof dateStr === "number") {
    const d = new Date(dateStr > 1e11 ? dateStr : dateStr * 1000);
    return isNaN(d.getTime()) ? null : d;
  }
  let s = String(dateStr).trim();
  if (!s) return null;
  // If ISO string without timezone indicator (e.g. 2026-10-17T09:12:33 or 2026-10-17T09:16:36.258249)
  if (s.includes("T") && !s.endsWith("Z") && !/[+-]\d{2}(:\d{2})?$/.test(s)) {
    s += "Z";
  }
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Format date to 24h Vietnam/local time: HH:mm:ss DD/MM/YYYY
 */
export function formatDateTime(dateStr?: string | null | number): string {
  const d = parseUtcDate(dateStr);
  if (!d) return "-";
  return d.toLocaleString("vi-VN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * Format time only: HH:mm:ss
 */
export function formatTime(dateStr?: string | null | number): string {
  const d = parseUtcDate(dateStr);
  if (!d) return "-";
  return d.toLocaleTimeString("vi-VN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

