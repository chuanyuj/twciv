// 所得與房價顧問：各縣市家庭可支配所得、房價所得比與失業率。
import { esc, fin, colorScale, RAMPS } from "../core/util.js";
import { money, dollars, pct, int, count3 } from "../core/fmt.js";
import { barList, rampLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, lensButton, sourcesHtml, topBy, frameBtn } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const { states } = data.levels;

  el.insertAdjacentHTML("beforeend", tiles([
    { label: "全國每戶可支配所得", value: dollars(n.median_income), sub: "主計總處 113年" },
    { label: "全國房價所得比", value: "10.76 倍", sub: "內政部 113Q4" },
    { label: "全國失業率", value: pct(n.unemployment), sub: "主計總處 113年" },
  ]));

  // --- 所得 vs 房價散佈圖 ---
  const aBody = section(el, { title: "所得與購屋負擔對照", note: "各縣市平均每戶可支配所得對中位數房價（推估）。虛線標示 8 倍、10 倍與 14 倍年所得線；拖曳框選可與地圖聯動。" });
  const aCtl = document.createElement("div");
  aCtl.className = "adv-row";
  aBody.appendChild(aCtl);
  for (const [id, label] of [["income", "家庭所得濾鏡"], ["home_ratio", "房價所得比濾鏡"]]) {
    const b = lensButton(app, id, label);
    if (b) aCtl.appendChild(b);
  }
  const ratioDomain = [6, 17];
  const ratioColor = colorScale({ type: "seq", domain: ratioDomain, ramp: RAMPS.heat });
  const ratioOf = (r) => (fin(r.v.price_income_ratio) ? r.v.price_income_ratio : (fin(r.v.home_value) && fin(r.v.median_income) ? r.v.home_value / r.v.median_income : null));
  const rows = states.rows.filter((r) => fin(r.v.median_income) && fin(r.v.home_value));

  const scatter = createScatter(aBody, {
    height: 300,
    points: rows.map((r) => ({ key: r.key, x: r.v.median_income, y: r.v.home_value, s: r.v.population, c: ratioOf(r), label: r.name, sub: "", row: r })),
    x: { label: "每戶可支配所得（元）", fmt: money, log: true },
    y: { label: "中位數房價推估（元）", fmt: money, log: true },
    size: { label: "人口數", fmt: count3, max: 14, min: 3 },
    refLines: [{ k: 8, label: "8×" }, { k: 10, label: "10×" }, { k: 14, label: "14×" }],
    color: (c) => ratioColor(c), colorLabel: "房價所得比", colorFmt: (v) => `${(+v).toFixed(1)} 倍`,
    labels: topBy(rows, (r) => r.v.population, { n: 8 }).map((x) => x.r.key),
    onHover: (p) => { link.hover(p ? rowsHighlight(states, [p.row]) : null); affTable.setHot(p ? p.key : null, false); },
    onClick: (p) => states.focus(p.row),
    onBrush: (set) => {
      const sel = set ? rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(states, sel, { dim: true }) : null, { frame: sel.length > 1 });
      affTable.setSelected(set);
      selInfo.innerHTML = sel.length ? `已選取 <b>${int(sel.length)}</b> 個縣市 · 共 ${count3(sel.reduce((a, r) => a + (r.v.population || 0), 0))} 人 ${frameBtn()}<button type="button" class="adv-mini" data-clear>清除</button>` : "";
    },
  });
  aBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.heat, domain: ratioDomain, fmt: (v) => `${v}倍`, label: "房價所得比" }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  aBody.appendChild(selInfo);
  const clearSel = () => { scatter.setSelected(null); affTable.setSelected(null); link.base(null); selInfo.innerHTML = ""; };
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) clearSel(); });

  aBody.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">各縣市所得與房價表</h4>`);
  const affTable = createTable(aBody, {
    caption: "各縣市家庭所得與房價所得比", rank: true, maxHeight: 280, rows, search: "搜尋縣市",
    columns: [
      { key: "name", label: "縣市", align: "l", value: (r) => r.name, html: (r) => esc(r.name) },
      { key: "inc", label: "可支配所得", value: (r) => r.v.median_income, text: (r) => money(r.v.median_income) },
      { key: "home", label: "推估房價", value: (r) => r.v.home_value, text: (r) => money(r.v.home_value) },
      { key: "ratio", label: "房價所得比", value: ratioOf, html: (r) => fin(ratioOf(r)) ? `<span class="dot" style="background:${ratioColor(ratioOf(r))}"></span>${ratioOf(r).toFixed(1)} 倍` : "–" },
    ],
    sort: { key: "ratio", dir: "desc" },
    onHover: (r) => { link.hover(r ? rowsHighlight(states, [r]) : null); scatter.setHot(r ? r.key : null); },
    onClick: (r) => states.focus(r),
  });

  // --- 368 鄉鎮市區 113 年度綜所稅中位數排行 ---
  const { counties } = data.levels;
  if (counties) {
    const fBody = section(el, { title: "368 鄉鎮市區綜所稅中位數排行（113年度）", note: "財政部財政資訊中心 113 年度村里綜合所得稅統計（依納稅單位加權聚合至 368 鄉鎮市區）。點擊列可飛至該鄉鎮。" });
    const fiaRows = counties.rows.filter((r) => fin(r.v.income));
    const fiaTable = createTable(fBody, {
      caption: "368 鄉鎮市區綜所稅中位數與平均數", rank: true, maxHeight: 280, rows: fiaRows, search: "搜尋鄉鎮市區（如竹北、大安、善化）",
      columns: [
        { key: "name", label: "鄉鎮市區", align: "l", value: (r) => r.name, html: (r) => esc(r.name) },
        { key: "income", label: "中位數", value: (r) => r.v.income, text: (r) => money(r.v.income), bar: { max: 1400000, color: "rgba(238,150,75,.4)" } },
        { key: "income_mean", label: "平均數", value: (r) => r.v.income_mean, text: (r) => money(r.v.income_mean) },
        { key: "population", label: "人口", value: (r) => r.v.population, text: (r) => count3(r.v.population) },
      ],
      sort: { key: "income", dir: "desc" },
      onHover: (r) => link.hover(r ? rowsHighlight(counties, [r]) : null),
      onClick: (r) => counties.focus(r),
    });
    ctx.cleanup(() => fiaTable.destroy());
  }

  // --- 失業率排行 ---
  const uBody = section(el, { title: "各縣市失業率排行（113年）", note: "行政院主計總處 113 年人力資源調查全年平均（金門與連江未納抽樣故不列）。" });
  const uHost = document.createElement("div");
  uBody.appendChild(uHost);
  const uRows = topBy(states.rows, (r) => r.v.unemployment, { n: 20 });
  const maxU = Math.max(0.01, ...uRows.map((x) => x.v));
  const mkU = (list) => list.map((x) => ({
    key: x.r.key, label: x.r.name, sub: "", value: x.v, text: pct(x.v),
    tone: x.v > n.unemployment * 1.02 ? "bad" : x.v < n.unemployment * 0.98 ? "good" : null, row: x.r,
  }));
  barList(uHost, {
    rows: mkU(uRows), max: maxU,
    onHover: (r) => link.hover(r ? rowsHighlight(states, [r.row]) : null),
    onClick: (r) => states.focus(r.row),
    ariaLabel: "各縣市失業率",
  });

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["dgbas", "moi_housing"], [
    "平均每戶可支配所得取自主計總處家庭收支調查，房價所得比取自內政部 113 年第 4 季房價負擔能力指標。",
    "澎湖、金門、連江未單獨公布房價所得比，人力資源調查亦未涵蓋金門與連江。",
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? states.rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      affTable.setHot(r ? r.key : null);
    },
    onEscape() {
      if (scatter.selected) { clearSel(); return true; }
      return false;
    },
  };
}
