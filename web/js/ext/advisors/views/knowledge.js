// 教育與科技顧問：368 鄉鎮市區大專以上學歷分佈、科技研發就業與所得關聯。
import { esc, fin, ratio, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { money, pct, int, count3, fmtShort } from "../core/fmt.js";
import { barList, histogram, rampLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, mapPicker, frameBtn, sourcesHtml, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { scienceLens } from "../core/lenses.js";

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const nation = app.data.nation;
  const { states, counties } = data.levels;
  const sci = nation.yields?.find((y) => y.key === "science");
  const twSci = n.yields?.science;
  const twShare = ratio(twSci, n.employed);
  const wavg = (k) => {
    if (!counties) return null;
    let a = 0, w = 0;
    for (const r of counties.rows) if (fin(r.v[k]) && fin(r.v.population)) { a += r.v[k] * r.v.population; w += r.v.population; }
    return w ? a / w : null;
  };

  el.insertAdjacentHTML("beforeend", tiles([
    { label: "科技研發就業", value: count3(twSci), sub: `占就業人口 ${pct(twShare)}`, color: sci?.color },
    { label: "大專以上學歷", value: pct(wavg("bachelors")), sub: "15 歲以上人口（113年）" },
    { label: "頂尖研究型大學", value: "7 所", sub: "地圖奇觀標示" },
  ]));

  const mapRow = document.createElement("div");
  mapRow.className = "adv-sec adv-mapsec";
  el.appendChild(mapRow);
  const picker = mapPicker(ctx, mapRow, {
    value: counties ? "degrees" : "science",
    options: [
      ...(counties ? [{ value: "degrees", label: "大專學歷", lens: () => "degrees" }] : []),
      { value: "science", label: "科技研發就業", lens: () => scienceLens(data) },
      { value: "terrain", label: "預設地形", lens: () => null },
    ],
  });

  // --- 科技研發產出排行 ---
  const sBody = section(el, { title: "科技研發就業排行", note: `${esc(sci?.description || "資訊通訊與專業科學技術服務業推估就業人數。")}` });
  const sHost = document.createElement("div");
  let mode = "share";
  segmented(sBody, { label: "排序依據", value: mode, options: [{ value: "share", label: "占就業比例" }, { value: "abs", label: "就業總人數" }], onChange: (v) => { mode = v; drawSci(); } });
  const sMap = document.createElement("button");
  sMap.type = "button";
  sMap.className = "adv-mini";
  sMap.textContent = "切換科技就業地圖";
  sMap.addEventListener("click", () => picker.set("science"));
  sBody.querySelector(".adv-seg")?.after(sMap);
  sBody.appendChild(sHost);
  const share = (r) => ratio(r.v.y_science, r.v.employed);
  function drawSci() {
    sHost.innerHTML = "";
    const list = mode === "abs" ? topBy(states.rows, (r) => r.v.y_science, { n: 12 }) : topBy(states.rows, share, { n: 12 });
    barList(sHost, {
      rank: true, ariaLabel: "科技研發就業排行",
      rows: list.map((x) => ({
        key: x.r.key, label: x.r.name,
        sub: mode === "abs" ? pct(share(x.r)) : `全國 ${twShare ? (share(x.r) / twShare).toFixed(2) : "1.0"}×`,
        value: x.v, text: mode === "abs" ? count3(x.v) : pct(x.v), color: sci?.color, row: x.r,
      })),
      onHover: (r) => link.hover(r ? rowsHighlight(states, [r.row]) : null),
      onClick: (r) => states.focus(r.row),
    });
  }
  drawSci();

  if (!counties) {
    el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["moi_ris"], []));
    return {};
  }

  // --- 368 鄉鎮大專學歷分佈與排行 ---
  const dBody = section(el, { title: "368 鄉鎮大專以上學歷 × 縣市所得", note: "橫軸為各鄉鎮 15 歲以上大專（含專科、大學、研究所）學歷比例，縱軸為所屬縣市每戶可支配所得，顏色為人口密度。拖曳可框選並聯動地圖。" });
  const dDom = robustDomain(counties.rows.map((r) => r.v.density), 0.02, true) || [10, 20000];
  const dColor = colorScale({ type: "seq", domain: dDom, log: true, ramp: RAMPS.seq });
  const scatter = createScatter(dBody, {
    height: 290,
    points: counties.rows.map((r) => ({ key: r.key, x: r.v.bachelors, y: r.v.income, s: r.v.population, c: r.v.density, label: r.name, sub: r.sub, row: r })),
    x: { label: "大專以上學歷比例", fmt: (v) => fmtShort("pct", v) },
    y: { label: "縣市每戶可支配所得", fmt: money, log: true },
    size: { label: "人口數", fmt: count3, max: 14, min: 1.5 },
    color: (c) => dColor(c), colorLabel: "人口密度", colorFmt: (v) => `${int(v)} 人/km²`,
    labels: topBy(counties.rows, (r) => r.v.bachelors, { n: 6 }).map((x) => x.r.key),
    onHover: (p) => link.hover(p ? rowsHighlight(counties, [p.row]) : null),
    onClick: (p) => counties.focus(p.row),
    onBrush: (set) => {
      const sel = set ? counties.rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(counties, sel, { dim: true }) : null, { frame: sel.length > 1 });
      selInfo.innerHTML = sel.length ? `已選取 <b>${int(sel.length)}</b> 個鄉鎮 · 共 ${count3(sel.reduce((a, r) => a + (r.v.population || 0), 0))} 人 ${frameBtn()}<button type="button" class="adv-mini" data-clear>清除</button>` : "";
    },
  });
  dBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.seq, domain: dDom, log: true, fmt: (v) => fmtShort("float", v), label: "每平方公里人口數" }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  dBody.appendChild(selInfo);
  const clearSel = () => { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; };
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) clearSel(); });

  const bBody = section(el, { title: "各鄉鎮大專學歷比例分佈", note: "內政部戶政司 113 年村里教育程度（ODRP020）聚合至 368 鄉鎮市區。點擊表格列可飛至該地。" });
  const bHost = document.createElement("div");
  bBody.appendChild(bHost);
  const degHist = histogram(bHost, {
    values: counties.rows.map((r) => ({ key: r.key, v: r.v.bachelors })), bins: 25, domain: [0.15, 0.85], height: 120,
    fmt: (v) => fmtShort("pct", v), unitLabel: "個鄉鎮", label: "鄉鎮大專學歷比例直方圖",
    colorOf: (_, t) => colorScale({ type: "seq", domain: [0, 1], ramp: RAMPS.seq })(t),
    onHover: (bin) => link.hover(bin ? rowsHighlight(counties, bin.keys.map((k) => counties.byKey.get(k)), { dim: true }) : null),
  });
  const tbl = createTable(bBody, {
    caption: "鄉鎮市區大專以上學歷排行", rank: true, maxHeight: 260, search: "搜尋鄉鎮市區",
    rows: counties.rows.filter((r) => fin(r.v.bachelors)),
    columns: [
      { key: "name", label: "鄉鎮市區", align: "l", value: (r) => r.name, html: (r) => esc(r.name) },
      { key: "population", label: "人口", value: (r) => r.v.population, text: (r) => count3(r.v.population) },
      { key: "bachelors", label: "大專以上", value: (r) => r.v.bachelors, text: (r) => pct(r.v.bachelors), bar: { max: 0.85, color: "rgba(74,134,214,.4)" } },
      { key: "income", label: "縣市所得", value: (r) => r.v.income, text: (r) => money(r.v.income) },
    ],
    sort: { key: "bachelors", dir: "desc" },
    onHover: (r) => link.hover(r ? rowsHighlight(counties, [r]) : null),
    onClick: (r) => counties.focus(r),
  });
  ctx.cleanup(() => tbl.destroy());

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["moi_ris", "dgbas"], [
    "教育程度由內政部戶政司 113 年村里統計（ODRP020）彙整至 368 鄉鎮市區，包含專科、大學與碩博士（含肄業與畢業）。",
  ]));

  return {
    onMapHover(h) {
      const c = h.cell >= 0 ? counties.rowAtCell(h.cell) : null;
      scatter.setHot(c ? c.key : null);
      degHist.setHot(c ? degHist.binOf(c.v.bachelors)?.i ?? null : null);
    },
    onEscape() {
      if (scatter.selected) { clearSel(); return true; }
      return false;
    },
  };
}
