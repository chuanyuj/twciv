// 地形與土地顧問：全臺地表覆蓋組成、22 縣市土地結構與農林漁牧就業排行。
import { esc, fin, ratio } from "../core/util.js";
import { pct, int, count3 } from "../core/fmt.js";
import { shareBar, barList, donut, smallMultiples } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, segmented, lensButton, sourcesHtml, topBy, frameBtn } from "../core/view.js";
import { LAND_KEYS, LAND_COLOR, rowsHighlight } from "../core/data.js";

const LAND_ZH = {
  forest: "森林",
  crop: "農田",
  pasture: "坡地牧園",
  grass: "草原",
  shrub: "灌叢",
  wetland: "濕地",
  developed: "都會建地",
};

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const w = app.w;
  const P = w.raw.pct;
  const owner = w.raw.owner;
  const { states } = data.levels;
  if (!P) {
    el.innerHTML = `<p class="adv-empty pad">尚未載入地表覆蓋資料。</p>`;
    return {};
  }

  const sums = Object.fromEntries(LAND_KEYS.map((k) => [k, 0]));
  const dominant = new Map(LAND_KEYS.map((k) => [k, []]));
  let cells = 0;
  for (let i = 0; i < w.grid.size; i++) {
    if (!(owner[i] >= 0)) continue;
    let tot = 0, best = null, bv = 0;
    for (const k of LAND_KEYS) {
      const v = P[k]?.[i] || 0;
      tot += v;
      if (v > bv) { bv = v; best = k; }
    }
    if (tot <= 0) continue;
    cells++;
    for (const k of LAND_KEYS) sums[k] += P[k]?.[i] || 0;
    dominant.get(best).push(i);
  }
  const share = Object.fromEntries(LAND_KEYS.map((k) => [k, cells ? sums[k] / (cells * 100) : 0]));
  const other = Math.max(0, 1 - LAND_KEYS.reduce((a, k) => a + share[k], 0));

  el.insertAdjacentHTML("beforeend", tiles([
    { label: "山林覆蓋", value: pct(share.forest, 0), sub: "全臺陸地六角格", color: LAND_COLOR.forest },
    { label: "平原農田", value: pct(share.crop + share.pasture, 0), sub: "耕地與坡地農牧", color: LAND_COLOR.crop },
    { label: "都會建地", value: pct(share.developed, 1), sub: "高密度居住與工商業", color: LAND_COLOR.developed },
  ]));

  // --- 全臺地表組成 ---
  const cBody = section(el, { title: "全臺地表覆蓋組成", kicker: "ESA WorldCover 10m", note: "依歐洲太空總署 ESA WorldCover 10 公尺衛星影像於全臺六角格取樣之真實地表覆蓋比例。游標移過色段可高亮該類主導區域，點擊可鎖定。" });
  let pinned = null;
  const parts = [...LAND_KEYS.map((k) => ({ key: k, label: LAND_ZH[k], value: share[k], color: LAND_COLOR[k], text: pct(share[k]) })), { key: "other", label: "其他（高山裸岩等）", value: other, color: "#6c6358", text: pct(other) }].filter((p) => p.value > 0.001).sort((a, b) => (a.key === "other") - (b.key === "other") || b.value - a.value);
  const domHighlight = (k, dim = true) => (dominant.has(k) ? { cells: new Set(dominant.get(k)), dimOthers: dim, color: LAND_COLOR[k] } : null);
  const sb = shareBar(cBody, {
    parts,
    onHover: (p) => link.hover(p && p.key !== "other" ? { ...domHighlight(p.key), color: "#fff3c4" } : null),
    onClick: (p) => pin(p.key === "other" || pinned === p.key ? null : p.key),
  });
  const pinInfo = document.createElement("div");
  pinInfo.className = "adv-brushinfo";
  cBody.appendChild(pinInfo);
  const lensRow = document.createElement("div");
  lensRow.className = "adv-row";
  for (const [id, label] of [["elevation", "地形海拔"], ["forest", "森林覆蓋"], ["crop", "農地覆蓋"], ["developed", "都會建成區"], ["quakes", "地震活動度"]]) {
    const b = lensButton(app, id, label);
    if (b) lensRow.appendChild(b);
  }
  cBody.appendChild(lensRow);
  function pin(k) {
    pinned = k;
    sb.setSelected(k);
    link.base(k ? domHighlight(k) : null, { frame: true });
    if (!k) { pinInfo.innerHTML = ""; return; }
    const n = dominant.get(k).length;
    pinInfo.innerHTML = `<b>${esc(LAND_ZH[k])}</b> 是 <b>${int(n)}</b> 個六角格的主導地貌（占陸地 ${pct(n / cells, 0)}），覆蓋率約 ${pct(share[k])}。
      ${frameBtn()}<button type="button" class="adv-mini" data-clear>清除</button>`;
  }
  pinInfo.addEventListener("click", (e) => {
    if (e.target.closest("[data-clear]")) pin(null);
  });

  // --- 各縣市土地組成 ---
  const sBody = section(el, { title: "22 縣市地表結構", note: "依任一地貌類型排序；游標移過可於地圖標示該縣市，點擊進入檢視。" });
  const stRows = states.rows.filter((r) => LAND_KEYS.some((k) => fin(r.v[`land_${k}`])));
  const comp = (r) => `<span class="adv-minibar">${LAND_KEYS.map((k) => {
    const v = r.v[`land_${k}`];
    return fin(v) && v > 0 ? `<i style="width:${(v * 100).toFixed(2)}%;background:${LAND_COLOR[k]}" title="${esc(`${LAND_ZH[k]} ${pct(v)}`)}"></i>` : "";
  }).join("")}</span>`;
  const domOf = (r) => LAND_KEYS.reduce((b, k) => ((r.v[`land_${k}`] ?? -1) > (r.v[`land_${b}`] ?? -1) ? k : b), LAND_KEYS[0]);
  let sortKey = "forest";
  const colsFor = (k) => [
    { key: "name", label: "縣市", align: "l", width: "minmax(0,1.0fr)", value: (r) => r.name, text: (r) => r.name },
    { key: "comp", label: "地表組成", align: "l", width: "minmax(0,1.5fr)", value: (r) => r.v[`land_${k}`], html: comp, title: `依${LAND_ZH[k]}排序` },
    { key: "share", label: LAND_ZH[k], value: (r) => r.v[`land_${k}`], html: (r) => `<span class="dot" style="background:${LAND_COLOR[k]}"></span>${pct(r.v[`land_${k}`], 0)}` },
    { key: "dom", label: "主導", align: "l", width: "minmax(0,.9fr)", value: (r) => LAND_ZH[domOf(r)], text: (r) => LAND_ZH[domOf(r)] },
  ];
  const sortSeg = document.createElement("div");
  sortSeg.className = "adv-row";
  sBody.appendChild(sortSeg);
  segmented(sortSeg, {
    label: "排序", value: sortKey,
    options: ["forest", "crop", "developed"].map((k) => ({ value: k, label: LAND_ZH[k] })),
    onChange: (k) => { sortKey = k; table.setColumns(colsFor(k), { key: "share", dir: "desc" }); drawShape(); },
  });
  let shape = "table";
  segmented(sortSeg, { label: "顯示", value: shape, options: [{ value: "table", label: "表格" }, { value: "grid", label: "圓餅圖" }], onChange: (v) => { shape = v; drawShape(); } });
  const tableHost = document.createElement("div");
  const gridHost = document.createElement("div");
  sBody.append(tableHost, gridHost);
  const table = createTable(tableHost, {
    caption: "各縣市地表覆蓋", rank: true, maxHeight: 300, rows: stRows, columns: colsFor(sortKey), sort: { key: "share", dir: "desc" },
    onHover: (r) => link.hover(r ? rowsHighlight(states, [r]) : null),
    onClick: (r) => states.focus(r),
  });
  let grid = null;
  function drawShape() {
    tableHost.hidden = shape !== "table";
    gridHost.hidden = shape !== "grid";
    if (shape !== "grid") return;
    gridHost.innerHTML = "";
    const sorted = [...stRows].sort((a, b) => (b.v[`land_${sortKey}`] ?? -1) - (a.v[`land_${sortKey}`] ?? -1));
    grid = smallMultiples(gridHost, {
      min: 92,
      items: sorted.map((r) => ({ key: r.key, label: r.v.abbr || r.key, sub: pct(r.v[`land_${sortKey}`], 0), row: r })),
      render: (cell, it) => donut(cell, {
        interactive: false, size: 62, thickness: 12,
        parts: LAND_KEYS.map((k) => ({ key: k, label: LAND_ZH[k], value: it.row.v[`land_${k}`], color: LAND_COLOR[k] })),
        center: { big: pct(it.row.v[`land_${sortKey}`], 0), small: "" },
        ariaLabel: `${it.row.name}`,
      }),
      onHover: (it) => link.hover(it ? rowsHighlight(states, [it.row]) : null),
      onClick: (it) => states.focus(it.row),
    });
  }
  drawShape();

  // --- 農林漁牧就業 ---
  const food = app.data.nation.yields?.find((y) => y.key === "food");
  const fBody = section(el, { title: "農林漁牧就業占比排行", note: `${esc(food?.description || "農林漁牧業推估就業人數。")} 依占各縣市總就業人口比例排序。` });
  const fHost = document.createElement("div");
  fBody.appendChild(fHost);
  const list = topBy(states.rows, (r) => ratio(r.v.y_food, r.v.employed), { n: 12 });
  barList(fHost, {
    rank: true, ariaLabel: "農林漁牧就業比例",
    rows: list.map((x) => ({ key: x.r.key, label: x.r.name, sub: `${count3(x.r.v.y_food)} 人`, value: x.v, text: pct(x.v), color: food?.color, row: x.r })),
    onHover: (r) => link.hover(r ? rowsHighlight(states, [r.row]) : null),
    onClick: (r) => states.focus(r.row),
  });

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["etopo", "moi_ris"], [
    "地表覆蓋依 NOAA ETOPO1 高程與鄉鎮人口密度分級推估，忠實反映山脈、平原農地與都會核心分佈。",
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? states.rowAtCell(h.cell) : null;
      table.setHot(r ? r.key : null);
      if (shape === "grid") grid?.setHot(r ? r.key : null);
      if (h.cell >= 0 && owner[h.cell] >= 0) {
        let best = null, bv = 0;
        for (const k of LAND_KEYS) { const v = P[k]?.[h.cell] || 0; if (v > bv) { bv = v; best = k; } }
        sb.setHot(best);
      } else sb.setHot(null);
    },
    onEscape() {
      if (pinned) { pin(null); return true; }
      return false;
    },
  };
}
