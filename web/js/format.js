export function compact(n) {
  if (n == null || Number.isNaN(n)) return "–";
  const a = Math.abs(n);
  if (a >= 1e12) return (n / 1e12).toFixed(a >= 1e13 ? 1 : 2).replace(/\.0+$/, "") + "兆";
  if (a >= 1e8) return (n / 1e8).toFixed(a >= 1e10 ? 0 : 1).replace(/\.0$/, "") + "億";
  if (a >= 1e4) return (n / 1e4).toFixed(a >= 1e6 ? 0 : 1).replace(/\.0$/, "") + "萬";
  return Math.round(n).toLocaleString("zh-TW");
}

export const money = (n) => (n == null ? "–" : "NT$" + compact(n));
export const dollars = (n) => (n == null ? "–" : "NT$" + Math.round(n).toLocaleString("zh-TW"));
export const int = (n) => (n == null ? "–" : Math.round(n).toLocaleString("zh-TW"));
export const pct = (x, d = 1) => (x == null ? "–" : (x * 100).toFixed(d) + "%");

export function yieldValue(y, v) {
  return y.unit === "usd" ? money(v) : compact(v);
}

export function popShort(n) {
  if (n == null || Number.isNaN(n)) return "–";
  if (n >= 1e4) return (n / 1e4).toFixed(n >= 1e6 ? 0 : 1).replace(/\.0$/, "") + "萬";
  return Math.round(n).toLocaleString("zh-TW");
}

export const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
