// 經濟產值顧問：各縣市營利事業銷售額、人均產值、產業結構與成長對照。
import { esc, fin, ratio, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { money, pct, int, signedPct, count3, fmtShort } from "../core/fmt.js";
import { barList, rampLegend, sizeLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, selectBox, sourcesHtml, frameBtn } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { icon } from "../../../ui/icon.js";
import { hasIcon } from "../../../icons.js";

const indIcon = (k) => (hasIcon(`i-${k}`) ? icon(`i-${k}`, "•", { size: 14 }) : "");

export function mount(ctx) {
  const { app, data, el, link, params } = ctx;
  const nation = app.data.nation;
  const n = nation.nation || {};
  const metros = data.levels.metros;
  const rows = metros.rows;
  const jobInd = Object.keys(nation.industries || {});

  const topInd = Object.entries(n.jobs || {}).filter(([, v]) => fin(v)).sort((a, b) => b[1] - a[1])[0];
  el.insertAdjacentHTML("beforeend", tiles([
    { label: `全臺營利事業銷售額 (${n.gdp_year || 2023})`, value: money(n.gdp), sub: "財政部縣市經濟規模指標" },
    { label: "人均銷售額", value: money(ratio(n.gdp, n.population)), sub: "銷售額 ÷ 總人口" },
    { label: "最大就業產業", value: topInd ? (nation.industries?.[topInd[0]] || topInd[0]).slice(0, 8) : "–", sub: topInd ? `占總就業 ${pct(topInd[1] / n.employed)}` : "" },
  ]));

  // --- 地圖泡泡：各縣市營利事業銷售額 ---
  const mapBody = section(el, { title: "各縣市經濟規模泡泡圖", note: "圓圈面積代表該縣市營利事業全年銷售額，顏色代表人均銷售額。游標移過查看數值，點擊開啟該縣市。" });
  const ppDomain = robustDomain(rows.map((r) => r.v.gdp_pc), 0.03, true) || [500000, 6000000];
  const ppColor = colorScale({ type: "seq", domain: ppDomain, ramp: RAMPS.gold });
  const gMax = Math.max(1, ...rows.map((r) => r.v.gdp || 0));
  const bubbles = ctx.bubbles("gdp", {
    rMax: 32, minR: 3, alpha: 0.62,
    tip: (b) => `<b>${esc(b.row.ref.full || b.row.name)}</b><br>銷售額 <b>${money(b.row.v.gdp)}</b> · 人均 <b>${money(b.row.v.gdp_pc)}</b><br>人口 ${count3(b.row.v.population)} 人`,
    onHover: (b) => { table.setHot(b ? b.key : null); scatter.setHot(b ? b.key : null); link.hover(b ? rowsHighlight(metros, [b.row]) : null); },
    onClick: (b) => app.selectCity(b.row.ref),
  });
  const bubbleItems = rows.filter((r) => fin(r.v.gdp)).map((r) => ({ key: r.key, x: app.w.grid.cx(r.ref.cell), y: app.w.grid.cy(r.ref.cell), value: r.v.gdp, color: ppColor(r.v.gdp_pc), row: r }));
  bubbles.set(bubbleItems, { vMax: gMax });
  const showBubbles = document.createElement("label");
  showBubbles.className = "adv-check";
  showBubbles.innerHTML = `<input type="checkbox" checked> 在地圖上顯示經濟規模泡泡`;
  showBubbles.querySelector("input").addEventListener("change", (e) => bubbles.set(e.target.checked ? bubbleItems : [], { vMax: gMax }));
  mapBody.appendChild(showBubbles);
  mapBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.gold, domain: ppDomain, fmt: money, label: "人均營利事業銷售額" })
    + sizeLegend([1e11, 1e12, 1e13].filter((v) => v <= gMax), (v) => 32 * Math.sqrt(v / gMax), money, "圓圈面積 = 全年銷售額"));

  // --- 縣市排行 ---
  const lBody = section(el, { title: "22 縣市經濟產值排行", note: "可切換總銷售額、人均銷售額或 2021–2024 人口成長率排序。" });
  segmented(lBody, {
    label: "排序", value: "gdp",
    options: [{ value: "gdp", label: "總銷售額" }, { value: "gdp_pc", label: "人均銷售額" }, { value: "growth", label: "人口成長" }],
    onChange: (v) => { table.setColumns(cols, { key: v, dir: "desc" }); },
  });
  const cols = [
    { key: "name", label: "縣市", align: "l", value: (r) => r.ref.full || r.name, html: (r) => esc(r.ref.full || r.name) },
    { key: "gdp", label: "銷售額", value: (r) => r.v.gdp, text: (r) => money(r.v.gdp), bar: { max: gMax, color: "rgba(224,181,76,.35)" } },
    { key: "gdp_pc", label: "人均", value: (r) => r.v.gdp_pc, text: (r) => money(r.v.gdp_pc) },
    { key: "growth", label: "人口變化", value: (r) => r.v.growth, text: (r) => signedPct(r.v.growth) },
  ];
  const table = createTable(lBody, {
    caption: "各縣市營利事業銷售額", columns: cols, rows, sort: { key: "gdp", dir: "desc" }, rank: true, maxHeight: 280,
    search: "搜尋縣市",
    onHover: (r) => { link.hover(r ? rowsHighlight(metros, [r]) : null); bubbles.setHot(r ? r.key : null); scatter.setHot(r ? r.key : null); },
    onClick: (r) => app.selectCity(r.ref),
  });

  // --- 產業區位商數 (專精程度) ---
  const specBody = section(el, { title: "產業專精程度（區位商數 LQ）", note: "區位商數 = 該縣市該業就業占比 ÷ 全國占比。×1.5 代表該縣市在此產業的集中度為全國平均的 1.5 倍。" });
  let industry = params.industry && jobInd.includes(params.industry) ? params.industry : "manufacturing";
  selectBox(specBody, {
    label: "產業別", value: industry,
    options: jobInd.map((k) => ({ value: k, label: nation.industries[k] })),
    onChange: (v) => setIndustry(v),
  });
  const lq = (r, k = industry) => {
    const o = r.ref;
    const tw = ratio(n.jobs?.[k], n.employed);
    return tw ? ratio(ratio(o.jobs?.[k], o.employed), tw) : null;
  };
  const specTable = createTable(specBody, {
    caption: "各縣市產業專精排行", rank: true, maxHeight: 240, rows: [],
    columns: [
      { key: "name", label: "縣市", align: "l", value: (r) => r.ref.full || r.name, html: (r) => esc(r.ref.full || r.name) },
      { key: "share", label: "就業占比", value: (r) => ratio(r.ref.jobs?.[industry], r.ref.employed), text: (r) => pct(ratio(r.ref.jobs?.[industry], r.ref.employed)) },
      { key: "lq", label: "區位商數", value: (r) => lq(r), text: (r) => (fin(lq(r)) ? `×${lq(r).toFixed(2)}` : "–"), bar: { max: 2.5, color: "rgba(74,134,214,.4)" } },
      { key: "workers", label: "推估人數", value: (r) => r.ref.jobs?.[industry], text: (r) => count3(r.ref.jobs?.[industry]) },
    ],
    sort: { key: "lq", dir: "desc" },
    onHover: (r) => { link.hover(r ? rowsHighlight(metros, [r]) : null); scatter.setHot(r ? r.key : null); bubbles.setHot(r ? r.key : null); },
    onClick: (r) => app.selectCity(r.ref),
  });

  // --- 人均產值 vs 人口成長散佈圖 ---
  const scBody = section(el, { title: "人均產值 × 人口成長", note: "橫軸為人均營利事業銷售額，縱軸為 2021–2024 人口成長率，圓點大小為人口數。可框選並與地圖聯動。" });
  const scatter = createScatter(scBody, {
    points: rows.map((r) => ({ key: r.key, x: r.v.gdp_pc, y: r.v.growth, s: r.v.population, c: r.v.median_income, label: r.ref.full || r.name, sub: "", row: r })),
    height: 280,
    x: { label: "人均銷售額（元）", fmt: money, log: true },
    y: { label: "人口成長率", fmt: (v) => fmtShort("signed", v) },
    size: { label: "人口數", fmt: count3, max: 14, min: 3 },
    refY: [{ v: n.growth ?? 0, label: `全國 ${signedPct(n.growth)}` }],
    labels: rows.slice(0, 8).map((r) => r.key),
    onHover: (p) => { link.hover(p ? rowsHighlight(metros, [p.row]) : null); bubbles.setHot(p ? p.key : null); table.setHot(p ? p.key : null, false); },
    onClick: (p) => app.selectCity(p.row.ref),
    onBrush: (set) => {
      const sel = set ? rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(metros, sel, { dim: true }) : null, { frame: sel.length > 1 });
      selInfo.innerHTML = sel.length ? `已選取 <b>${int(sel.length)}</b> 個縣市 · 總銷售額 ${money(sel.reduce((a, r) => a + (r.v.gdp || 0), 0))} ${frameBtn()}<button type="button" class="adv-mini" data-clear>清除</button>` : "";
    },
  });
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  scBody.appendChild(selInfo);
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; } });

  function setIndustry(k) {
    industry = k;
    specTable.setRows(rows);
  }
  setIndustry(industry);

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["mof_sales", "dgbas", "moi_ris"], [
    "因主計總處未編布縣市別 GDP，本面板採財政部各縣市營利事業全年銷售額作經濟規模指標（大型企業總部設籍於臺北市會使北市數值偏高）。",
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? metros.rowAtCell(h.cell) : null;
      table.setHot(r ? r.key : null);
      scatter.setHot(r ? r.key : null);
      bubbles.setHot(r ? r.key : null);
    },
    onEscape() {
      if (scatter.selected) { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; return true; }
      return false;
    },
  };
}
