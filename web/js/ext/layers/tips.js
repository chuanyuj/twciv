// Hover tooltips for the map-art layers (Traditional Chinese, Taiwan sources).
import { esc, compact, int } from "../../format.js";

const muted = (s) => `<span class="muted">${s}</span>`;
const num = (n) => (n == null || !Number.isFinite(n) ? "–" : compact(n));
const sign = (x) => (x > 0 ? "+" : x < 0 ? "−" : "±");

const HUB_NAME = { L: "國際樞紐機場", M: "主要國際機場", S: "區域與離島樞紐機場", N: "地方航空站" };
const PORT_TYPE = { coastal: "國際商港", great_lakes: "商港", inland: "內陸港" };
const WONDER_ZH = {
  natural: "國家公園／自然奇觀",
  coastal: "海岸國家公園",
  monument: "歷史紀念公園",
  recreation: "風景名勝",
  university: "頂尖研究型大學",
  landmark: "代表性地標",
};

export const tips = {
  port(p) {
    const yr = p.year ?? "";
    const lines = [
      `<b>${esc(p.name)}</b> ${muted(`${esc(PORT_TYPE[p.type] || "商港")} · ${esc(p.state || "")}`)}`,
      `全台第 ${esc(p.rank)} 大商港 · 年吞吐量約 <b>${num(p.tons)}</b> 公噸（${esc(yr)}）`,
      muted("資料來源：臺灣港務股份有限公司。"),
    ];
    return lines.join("<br>");
  },
  airport(a) {
    const lines = [`<b>${esc(a.id)} · ${esc(a.name)}</b> ${muted(esc(a.city || a.state || ""))}`];
    lines.push(a.hub ? esc(HUB_NAME[a.hub] || a.hub) : "航空站");
    if (a.enplanements != null) {
      let ch = "";
      if (a.enplanements_prev > 0) {
        const r = a.enplanements / a.enplanements_prev - 1;
        ch = `（較 ${a.year - 1} 年 ${sign(r)}${Math.abs(r * 100).toFixed(1)}%）`;
      }
      lines.push(`${esc(a.year)} 年客運量約 <b>${num(a.enplanements)}</b> 人次${ch}`);
    }
    if (a.cargo_lbs != null) lines.push(`年貨運量約 ${num(a.cargo_lbs)} 公斤`);
    lines.push(muted("資料來源：交通部民用航空局。"));
    return lines.join("<br>");
  },
  fort(f) {
    return `<b>${esc(f.name)}</b> ${muted(esc(f.state || ""))}`;
  },
  range(r) {
    return `<b>${esc(r.name)}</b> ${muted(esc(r.state || ""))}`;
  },
  wonder(x) {
    const k = WONDER_ZH[x.kind] || "臺灣奇觀";
    const lines = [`<b>${esc(x.name)}</b> ${muted(esc(x.state || ""))}`];
    lines.push(esc(k));
    if (x.students != null) lines.push(`在校學生約 <b>${int(x.students)}</b> 人`);
    if (x.visits != null) lines.push(`年訪客量約 <b>${num(x.visits)}</b> 人次`);
    if (x.description) lines.push(muted(esc(x.description)));
    return lines.join("<br>");
  },
  route(rt) {
    const a = rt.a?.short || rt.a?.name || "", b = rt.b?.short || rt.b?.name || "";
    return `<b>${esc(a)} ⇄ ${esc(b)}</b>`;
  },
};
