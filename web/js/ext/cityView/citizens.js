// 城市視角「市民結構」列：以小人像視覺化年齡世代與教育程度（內政部戶政司 ODRP014 / ODRP020）。
import { esc, int, pct } from "../../format.js";
import { compact } from "./fmt.js";
import { CATEGORY_COLOR, figureCanvas, loadPainter } from "./figures.js";

const ROWS = [
  { id: "workforce", title: "職業結構", sub: "依職業別", noun: "就業者", n: null },
  { id: "age", title: "年齡世代", sub: "依年齡層（113年12月戶籍人口）", noun: "居民", n: null },
  { id: "commute", title: "通勤方式", sub: "依交通工具", noun: "通勤者", n: null },
  { id: "education", title: "教育程度", sub: "15 歲以上人口（113年）", noun: "15歲以上人口", n: 10 },
  { id: "nativity", title: "出生地", sub: "依出生地", noun: "居民", n: 10 },
];

const PHRASE = {
  age: {
    child: "為 0–14 歲幼年人口",
    young: "為 15–39 歲青壯年人口",
    midlife: "為 40–64 歲中壯年人口",
    elder: "為 65 歲以上高齡人口",
  },
  education: {
    less_than_hs: "為國中及以下學歷",
    high_school: "為高中職學歷",
    some_college: "為專科學歷",
    bachelors: "為大學學歷",
    graduate: "為碩博士學歷",
  },
};

const SHORT = {
  age: { child: "0–14歲", young: "15–39歲", midlife: "40–64歲", elder: "65歲+" },
  education: { less_than_hs: "國中以下", high_school: "高中職", some_college: "專科", bachelors: "大學", graduate: "碩博士" },
};

export function largestRemainder(counts, keys, n) {
  const tot = keys.reduce((a, k) => a + (counts[k] || 0), 0);
  if (!(tot > 0)) return null;
  const raw = keys.map((k) => ((counts[k] || 0) / tot) * n);
  const out = raw.map(Math.floor);
  let left = n - out.reduce((a, v) => a + v, 0);
  const order = raw.map((v, j) => [v - Math.floor(v), j]).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  for (let k = 0; k < left; k++) out[order[k][1]]++;
  return Object.fromEntries(keys.map((k, j) => [k, out[j]]));
}

export function oneIn(share) {
  if (share == null || !Number.isFinite(share)) return null;
  if (share <= 0) return { text: "極少", plural: true };
  if (share < 0.001) return { text: "不到千分之 1", plural: false };
  if (share >= 0.3) {
    const k = Math.round(share * 10);
    return k >= 10 ? { text: "幾乎全部", plural: true } : { text: `每 10 位中約 ${k} 位`, plural: true };
  }
  const n = Math.round(1 / share);
  return { text: `每 ${int(n)} 位中約 1 位`, plural: false };
}

function sentence(rowId, key, share, natShare, cityName, noun) {
  const a = oneIn(share);
  if (!a) return "";
  const ph = PHRASE[rowId]?.[key] || "屬於此類別";
  const tw = natShare != null ? `（全國 ${pct(natShare, 1)}）` : "";
  return `${cityName}${noun}中，${a.text}${ph}${tw}`;
}

function rowModel(rowDef, row, nat, groups, figuresN) {
  const keys = (groups[rowDef.id] || []).map((g) => g.key);
  const n = figuresN[rowDef.id] ?? rowDef.n ?? 10;
  const figs = row.figures || largestRemainder(row.counts || {}, keys, n);
  const natFigs = nat?.figures || (nat ? largestRemainder(nat.counts || {}, keys, n) : null);
  return { keys, n, figs, natFigs };
}

function specMap(city) {
  const m = new Map();
  for (const s of city?.specialists || []) m.set(`${s.row}|${s.key}`, s);
  return m;
}

export function citizensHtml(m, data) {
  const c = m.city;
  if (data === undefined) return `<p class="muted cv-note">正在載入市民結構資料…</p>`;
  if (!data || !data.cities) return `<p class="muted cv-note">尚未載入市民結構資料。</p>`;
  const row0 = data.cities[c.id];
  if (!row0) return `<p class="muted cv-note">此縣市無市民結構統計資料。</p>`;

  const nat = data.national || {};
  const groups = data.groups || {};
  const specs = specMap(row0);
  const label = Object.fromEntries(Object.entries(groups).map(([r, gs]) => [r, Object.fromEntries(gs.map((g) => [g.key, g.label]))]));

  const med = row0.age?.median, twMed = nat.age?.median;
  const ba = row0.education?.bachelors_plus, twBa = nat.education?.bachelors_plus;
  const eld = row0.age?.shares?.elder, twEld = nat.age?.shares?.elder;

  const chip = (v, tw, fmt, lbl, tip) =>
    (v == null ? "" : `<div class="cv-cz-chip" title="${esc(tip)}"><b>${fmt(v)}</b><span>${esc(lbl)}</span>${tw != null ? `<small>全國 ${fmt(tw)}</small>` : ""}</div>`);

  // 只顯示臺灣有實際資料的列（略過未發布的職業/通勤/出生地，不顯示空白英文警語）
  const rows = ROWS.filter((rd) => row0[rd.id]).map((rd) => {
    const row = row0[rd.id];
    const head = `<div class="cv-cz-h"><b>${esc(rd.title)}</b><span>${esc(rd.sub)}</span></div>`;
    const { keys, n, figs } = rowModel(rd, row, nat[rd.id], groups, data.figures || {});
    if (!figs) return "";
    const per = row.total / n;
    const cells = [];
    for (const k of keys) {
      for (let j = 0; j < (figs[k] || 0); j++) {
        const sp = specs.get(`${rd.id}|${k}`);
        const mark = sp ? (sp.ratio >= 1 ? "up" : "down") : "";
        cells.push(`<span class="cv-fig${mark ? ` ${mark}` : ""}" tabindex="${j ? -1 : 0}" role="img" data-k="${esc(k)}" aria-label="${esc(label[rd.id]?.[k] || k)}"></span>`);
      }
    }
    const legend = keys.map((k) => {
      const sh = row.shares?.[k], tw = nat[rd.id]?.shares?.[k];
      return `<span class="cv-cz-k${figs[k] ? "" : " zero"}" data-k="${esc(k)}" title="${esc(label[rd.id]?.[k] || k)}：${sh != null ? pct(sh, 1) : "–"}${tw != null ? `（全國 ${pct(tw, 1)}）` : ""}"><i style="background:${esc(CATEGORY_COLOR[rd.id]?.[k] || "#888")}"></i>${esc(SHORT[rd.id]?.[k] || k)} <small>${sh != null ? pct(sh, 0) : "–"}</small></span>`;
    }).join("");
    const twBar = nat[rd.id]?.shares ? `<div class="cv-cz-us" title="全國比例對照（同順序）"><span>全國</span><div>${keys.map((k) => {
      const s = nat[rd.id].shares[k] || 0;
      return s > 0 ? `<i style="flex:${s};background:${esc(CATEGORY_COLOR[rd.id]?.[k] || "#888")}" title="${esc(SHORT[rd.id]?.[k] || k)}：全國 ${pct(s, 1)}"></i>` : "";
    }).join("")}</div></div>` : "";
    const cap = `每個人像約代表 ${compact(per)} 位${rd.noun} · 總計 ${compact(row.total)} 人`;
    const extra = rd.id === "age" && med != null ? ` · 年齡中位數 ${med.toFixed(1)} 歲${twMed != null ? `（全國 ${twMed.toFixed(1)} 歲）` : ""}` : "";
    return `<div class="cv-cz-row" data-row="${rd.id}" style="--n:${n}">${head}
      <div class="cv-figs" role="group" aria-label="${esc(rd.title)}">${cells.join("")}</div>
      ${twBar}
      <div class="cv-cz-out" aria-live="polite" data-default="${esc(cap + extra)}">${esc(cap + extra)}</div>
      <div class="cv-cz-legend">${legend}</div>
    </div>`;
  }).join("");

  return `
    <div class="cv-cz-top">
      ${chip(med, twMed, (v) => v.toFixed(1) + " 歲", "年齡中位數", "113年12月單歲戶籍人口中位數")}
      ${chip(eld, twEld, (v) => pct(v, 1), "65歲以上高齡", "65歲以上人口占總人口比例（>20%為超高齡）")}
      ${chip(ba, twBa, (v) => pct(v, 0), "大學以上學歷", "15歲以上具大學或碩博士學歷比例")}
    </div>
    <div class="cv-cz">${rows}</div>
    <p class="cv-note">資料來源：${esc(data.vintage || "內政部戶政司 113年12月")}。人像數量採最大餘數法四捨五入至 10 人；游標移過或點擊人像可查看精確比例與人數。</p>`;
}

export function mountCitizens(host, m, data) {
  if (!host || !data?.cities?.[m.city.id]) return;
  const row0 = data.cities[m.city.id];
  const nat = data.national || {};
  const dpr = Math.min(3, Math.max(1, Math.round((devicePixelRatio || 1) * 2) / 2));
  const paintAll = () => {
    host.querySelectorAll(".cv-cz-row[data-row]").forEach((rowEl) => {
      const rid = rowEl.dataset.row;
      rowEl.querySelectorAll(".cv-fig").forEach((el) => {
        const src = figureCanvas(rid, el.dataset.k, 36, dpr);
        const cv = document.createElement("canvas");
        cv.width = src.width;
        cv.height = src.height;
        cv.getContext("2d").drawImage(src, 0, 0);
        el.replaceChildren(cv);
      });
    });
  };
  paintAll();
  loadPainter().then(() => { if (host.isConnected) paintAll(); });

  host.querySelectorAll(".cv-cz-row[data-row]").forEach((rowEl) => {
    const rid = rowEl.dataset.row;
    const rd = ROWS.find((r) => r.id === rid);
    const row = row0[rid];
    const out = rowEl.querySelector(".cv-cz-out");
    if (!row || !out) return;
    const show = (k) => {
      rowEl.querySelectorAll("[data-k]").forEach((el) => el.classList.toggle("lit", el.dataset.k === k));
      rowEl.classList.toggle("focus", !!k);
      if (!k) {
        out.textContent = out.dataset.default;
        out.classList.remove("on");
        return;
      }
      const sh = row.shares?.[k], tw = nat[rid]?.shares?.[k];
      out.innerHTML = `${esc(sentence(rid, k, sh, tw, m.city.full || m.city.name, rd.noun))}<small>本縣市 ${sh != null ? pct(sh, 1) : "–"}${tw != null ? ` · 全國 ${pct(tw, 1)}` : ""}${row.counts?.[k] != null ? ` · 約 ${compact(row.counts[k])} 人` : ""}</small>`;
      out.classList.add("on");
    };
    let pinned = null;
    rowEl.addEventListener("pointerover", (e) => {
      const el = e.target.closest("[data-k]");
      if (el && rowEl.contains(el)) show(el.dataset.k);
    });
    rowEl.addEventListener("pointerleave", () => show(pinned));
    rowEl.addEventListener("focusin", (e) => {
      const el = e.target.closest("[data-k]");
      if (el) show(el.dataset.k);
    });
    rowEl.addEventListener("focusout", () => show(pinned));
    rowEl.addEventListener("click", (e) => {
      const el = e.target.closest("[data-k]");
      if (!el) return;
      pinned = pinned === el.dataset.k ? null : el.dataset.k;
      show(pinned);
    });
  });
}
