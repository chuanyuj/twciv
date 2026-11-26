// 人口與高齡顧問：22 縣市人口成長、368 鄉鎮市區人口密度、年齡中位數與 65 歲以上高齡比例。
import { esc, fin, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { pct, int, signedPct, count3, fmtShort, fmtValue } from "../core/fmt.js";
import { barList, histogram, rampLegend } from "../core/charts.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, mapPicker, frameBtn, sourcesHtml, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { growthLens } from "../core/lenses.js";

export function mount(ctx) {
  const { data, el, link } = ctx;
  const n = data.nat;
  const { states, counties } = data.levels;
  const yrs = n.growth_years || [2021, 2024];

  el.insertAdjacentHTML("beforeend", tiles([
    { label: "全國總人口", value: count3(n.population), sub: data.vintage },
    { label: `人口變化 ${yrs.join("–")}`, value: signedPct(n.growth, 2), sub: "內政部戶政司" },
    { label: "行政區規模", value: `${int(states.rows.length)} 縣市`, sub: counties ? `${int(counties.rows.length)} 鄉鎮市區` : "" },
  ]));

  const mapRow = document.createElement("div");
  mapRow.className = "adv-sec adv-mapsec";
  el.appendChild(mapRow);
  const lensOpt = (value, label, id) => ({ value, label, lens: () => id });
  const picker = mapPicker(ctx, mapRow, {
    value: "growth",
    options: [
      { value: "growth", label: "人口成長", lens: () => "growth" },
      ...(counties ? [lensOpt("density", "人口密度", "density"), lensOpt("elderly", "高齡比例", "elderly"), lensOpt("age", "年齡中位數", "age")] : []),
      { value: "terrain", label: "預設地形", lens: () => null },
    ],
  });

  // --- 22 縣市人口成長排行 ---
  const gBody = section(el, { title: "人口成長與流失排行", note: `2021–2024 年各縣市戶籍人口變化率（內政部戶政司 ODRP048）。點擊可於地圖聚焦該縣市。` });
  const gHost = document.createElement("div");
  gBody.appendChild(gHost);
  const fast = topBy(states.rows, (r) => r.v.growth, { n: 8 });
  const slow = topBy(states.rows, (r) => r.v.growth, { n: 8, asc: true });
  const maxG = Math.max(0.01, ...[...fast, ...slow].map((x) => Math.abs(x.v)));
  const mkG = (list) => list.map((x) => ({ key: x.r.key, label: x.r.name, sub: "", value: x.v, text: signedPct(x.v), tone: x.v >= 0 ? "good" : "bad", row: x.r }));
  const gOpts = {
    diverging: true, max: maxG,
    onHover: (r) => link.hover(r ? rowsHighlight(states, [r.row]) : null),
    onClick: (r) => states.focus(r.row),
  };
  gHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">成長最快</h4>`);
  barList(gHost, { ...gOpts, rows: mkG(fast), ariaLabel: "成長最快縣市" });
  gHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">減少最多</h4>`);
  barList(gHost, { ...gOpts, rows: mkG(slow), ariaLabel: "減少最多縣市" });

  if (!counties) {
    el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["moi_ris"], []));
    return {};
  }

  // --- 368 鄉鎮市區人口密度 ---
  const dBody = section(el, { title: "368 鄉鎮市區人口密度分佈", note: "對數尺度顯示各鄉鎮每平方公里人口數。切換至「按人口加權」可看出多數臺灣民眾高度集中在高密度都會區；點擊長條可鎖定地圖範圍。" });
  const dCtl = document.createElement("div");
  dCtl.className = "adv-row";
  dBody.appendChild(dCtl);
  let weighted = false, pinnedBin = null;
  segmented(dCtl, { label: "統計方式", value: "counties", options: [{ value: "counties", label: "按鄉鎮數" }, { value: "people", label: "按人口加權" }], onChange: (v) => { weighted = v === "people"; drawHist(); } });
  const dLens = document.createElement("button");
  dLens.type = "button";
  dLens.className = "adv-mini";
  dLens.textContent = "切換人口密度濾鏡";
  dLens.addEventListener("click", () => picker.set("density"));
  dCtl.appendChild(dLens);
  const histHost = document.createElement("div");
  dBody.appendChild(histHost);
  const binInfo = document.createElement("div");
  binInfo.className = "adv-brushinfo";
  dBody.appendChild(binInfo);
  let hist = null;
  const twDensity = counties.rows.reduce((a, r) => a + (r.v.population || 0), 0) / Math.max(1, counties.rows.reduce((a, r) => a + (r.v.land_km2 || 0), 0));
  const cByKey = counties.byKey;
  function drawHist() {
    histHost.innerHTML = "";
    const vals = counties.rows.map((r) => ({ key: r.key, v: r.v.density, w: r.v.population }));
    hist = histogram(histHost, {
      values: vals, log: true, bins: 26, domain: [5, 45000], weighted, height: 130,
      fmt: (v) => fmtShort("float", v), unitLabel: "個鄉鎮", weightFmt: (w) => `${count3(w)} 人`,
      label: "鄉鎮市區人口密度直方圖",
      colorOf: (_, t) => colorScale({ type: "seq", domain: [0, 1], ramp: RAMPS.heat })(t),
      markers: [{ v: twDensity, label: `全台平均 ${int(twDensity)}` }],
      onHover: (bin) => link.hover(bin ? rowsHighlight(counties, bin.keys.map((k) => cByKey.get(k)), { dim: true }) : null),
      onClick: (bin) => {
        pinnedBin = pinnedBin === bin.i ? null : bin.i;
        const rows = pinnedBin != null ? bin.keys.map((k) => cByKey.get(k)) : [];
        link.base(rows.length ? rowsHighlight(counties, rows, { dim: true }) : null, { frame: rows.length > 1 });
        binInfo.innerHTML = rows.length ? `<b>${int(rows.length)}</b> 個鄉鎮（${fmtShort("float", bin.x0)}–${fmtShort("float", bin.x1)} 人/km²）· 共 ${count3(rows.reduce((a, r) => a + (r.v.population || 0), 0))} 人 ${frameBtn()}<button type="button" class="adv-mini" data-clear>清除</button>` : "";
      },
    });
  }
  binInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { pinnedBin = null; link.base(null); binInfo.innerHTML = ""; } });
  drawHist();

  // --- 年齡中位數 × 65 歲以上高齡比例 ---
  const aBody = section(el, { title: "高齡化結構：年齡中位數 × 65 歲以上比例", note: "每個圓點代表一個鄉鎮市區，橫軸為年齡中位數、縱軸為 65 歲以上人口比例、大小為人口數、顏色為人口密度。可拖曳框選區域並與地圖聯動。" });
  const aCtl = document.createElement("div");
  aCtl.className = "adv-row";
  aBody.appendChild(aCtl);
  aCtl.innerHTML = `<span class="adv-note">切換地圖著色</span><button type="button" class="adv-mini" data-map="elderly">高齡比例</button><button type="button" class="adv-mini" data-map="age">年齡中位數</button>`;
  aCtl.addEventListener("click", (e) => { const v = e.target.closest("[data-map]")?.dataset.map; if (v) picker.set(v); });
  const dDom = robustDomain(counties.rows.map((r) => r.v.density), 0.02, true) || [10, 20000];
  const dColor = colorScale({ type: "seq", domain: dDom, log: true, ramp: RAMPS.heat });
  const big = topBy(counties.rows, (r) => r.v.population, { n: 6 }).map((x) => x.r.key);
  const scatter = createScatter(aBody, {
    height: 300,
    points: counties.rows.map((r) => ({ key: r.key, x: r.v.median_age, y: r.v.elderly, s: r.v.population, c: r.v.density, label: r.name, sub: r.sub, row: r })),
    x: { label: "年齡中位數（歲）", fmt: (v) => String(+v.toFixed(0)) },
    y: { label: "65歲以上比例", fmt: (v) => fmtShort("pct", v) },
    size: { label: "人口數", fmt: count3, max: 14, min: 1.5 },
    color: (c) => dColor(c), colorLabel: "人口密度", colorFmt: (v) => `${fmtValue("float", v)} 人/km²`,
    labels: big,
    refX: fin(medianOf(counties.rows, "median_age")) ? [{ v: medianOf(counties.rows, "median_age"), label: "鄉鎮中位數" }] : [],
    refY: [{ v: 0.2, label: "超高齡 20%" }],
    onHover: (p) => link.hover(p ? rowsHighlight(counties, [p.row]) : null),
    onClick: (p) => counties.focus(p.row),
    onBrush: (set) => {
      const sel = set ? counties.rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(counties, sel, { dim: true }) : null, { frame: sel.length > 1 });
      selInfo.innerHTML = sel.length ? selSummary(sel) : "";
    },
  });
  aBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.heat, domain: dDom, log: true, fmt: (v) => fmtShort("float", v), label: "每平方公里人口數" }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  aBody.appendChild(selInfo);
  function selSummary(sel) {
    const pop = sel.reduce((a, r) => a + (r.v.population || 0), 0);
    const top = [...sel].sort((a, b) => (b.v.population || 0) - (a.v.population || 0)).slice(0, 5);
    return `已選取 <b>${int(sel.length)}</b> 個鄉鎮 · 共 ${count3(pop)} 人（占全國 ${pct(pop / n.population)}）<br><span class="sub">最大：${top.map((r) => esc(r.name)).join(" · ")}</span> ${frameBtn()}<button type="button" class="adv-mini" data-clear>清除</button>`;
  }
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; } });

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["moi_ris"], [
    "人口密度、成長率與單歲年齡皆來自內政部戶政司 110–113 年官方開放資料（ODRP048 / ODRP014），涵蓋全台 368 鄉鎮市區零缺漏。",
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? counties.rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      hist?.setHot(r ? hist.binOf(r.v.density)?.i ?? null : null);
    },
    onEscape() {
      if (scatter.selected || pinnedBin != null) {
        scatter.setSelected(null); pinnedBin = null; link.base(null); selInfo.innerHTML = ""; binInfo.innerHTML = "";
        return true;
      }
      return false;
    },
  };
}

function medianOf(rows, k) {
  const s = rows.map((r) => r.v[k]).filter(fin).sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : null;
}
