// Number formatting for the advisor kit, built on web/js/format.js.
// Formats follow lenses.json / counties.json: int | usd | pct (0..1 fraction) | float | minutes | years | km2 | text,
// plus a few of our own: money (compact $), signed (signed %), lq (×1.23), mw, count, ratio (×4.2).
import { compact, dollars, int, money, pct } from "../../../format.js";
import { fin } from "./util.js";

export { compact, dollars, int, money, pct };

export const signedPct = (g, d = 1) => (fin(g) ? `${g >= 0 ? "+" : "−"}${Math.abs(g * 100).toFixed(d)}%` : "–");

// Counts to three significant figures (1.12M vs 1.11M rather than 1.1M twice).
export function count3(n) {
  if (!fin(n)) return "–";
  const a = Math.abs(n);
  const sig = (d, unit) => (n / d).toFixed(a / d >= 100 ? 0 : a / d >= 10 ? 1 : 2).replace(/\.0+$/, "") + unit;
  if (a >= 1e12) return sig(1e12, "兆");
  if (a >= 1e8) return sig(1e8, "億");
  if (a >= 1e4) return sig(1e4, "萬");
  return int(n);
}

export const mw = (v) => (fin(v) ? (Math.abs(v) >= 10000 ? `${(v / 1000).toFixed(v >= 1e5 ? 0 : 1)} GW` : `${int(v)} MW`) : "–");

/** Full-ish text for a value in a given format (tables, tooltips). */
export function fmtValue(format, v, unit) {
  if (format === "text") return v == null || v === "" ? "–" : String(v);
  if (!fin(v)) return "–";
  switch (format) {
    case "int": case "count": return Math.abs(v) >= 1e6 ? count3(v) : int(v);
    case "usd": return Math.abs(v) >= 1e6 ? money(v) : dollars(v);
    case "money": return money(v);
    case "pct": return pct(v);
    case "signed": return signedPct(v);
    case "lq": return `×${v.toFixed(2)}`;
    case "ratio": return `×${v.toFixed(1)}`;
    case "minutes": return `${v.toFixed(1)} 分鐘`;
    case "years": return `${v.toFixed(1)} 歲`;
    case "km2": return `${int(v)} km²`;
    case "mw": return mw(v);
    case "float": return Math.abs(v) >= 100 ? int(v) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
    default:
      if (unit === "MW") return mw(v);
      return Math.abs(v) >= 1e4 ? count3(v) : Math.abs(v) >= 100 ? int(v) : v.toFixed(2);
  }
}

/** Compact text for a table cell, so numbers fit narrow columns. */
export function fmtCell(format, v, unit) {
  if (format === "text") return v == null || v === "" ? "–" : String(v);
  if (!fin(v)) return "–";
  const a = Math.abs(v);
  switch (format) {
    case "int": case "count": return a >= 1e4 ? count3(v) : int(v);
    case "usd": return a >= 1e4 ? `NT$${count3(v)}` : dollars(v);
    case "money": return money(v);
    case "km2": return a >= 1e5 ? `${count3(v)} km²` : `${int(v)} km²`;
    case "float": return a >= 1e4 ? count3(v) : fmtValue(format, v, unit);
    default: return fmtValue(format, v, unit);
  }
}

/** Short text for axis ticks and chips. */
export function fmtShort(format, v) {
  if (!fin(v)) return "–";
  switch (format) {
    case "usd": case "money": return money(v);
    case "pct": return `${+(v * 100).toFixed(Math.abs(v) < 0.1 && v !== 0 ? 1 : 0)}%`;
    case "signed": return `${v > 0 ? "+" : v < 0 ? "−" : ""}${+Math.abs(v * 100).toFixed(1)}%`;
    case "lq": case "ratio": return `×${+v.toFixed(1)}`;
    case "mw": return mw(v);
    case "minutes": case "years": return String(+v.toFixed(0));
    default: return Math.abs(v) >= 1000 ? compact(v) : String(+v.toPrecision(3));
  }
}

/** Parse "150萬", "1.5M", "12%", "NT$80萬", "-3%" into a number in the field's units (pct → fraction). */
export function parseNum(text, format) {
  if (text == null) return null;
  let s = String(text).trim().replace(/(?:NT\$|[,$\s])/gi, "").replace(/^−/, "-");
  if (!s) return null;
  let isPct = false;
  if (s.endsWith("%")) { isPct = true; s = s.slice(0, -1); }
  const m = /^(-?\d*\.?\d+)([kmbt萬億兆]?)$/i.exec(s);
  if (!m) return null;
  const mult = { "": 1, k: 1e3, m: 1e6, b: 1e9, t: 1e12, "萬": 1e4, "億": 1e8, "兆": 1e12 };
  let v = parseFloat(m[1]) * mult[m[2].toLowerCase()];
  if ((format === "pct" || format === "signed") && (isPct || Math.abs(v) > 1)) v /= 100;
  return v;
}
