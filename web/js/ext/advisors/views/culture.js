// 奇觀與文化顧問：臺灣國家公園、頂尖研究型大學、代表性地標與文教觀光就業排行。
import { esc, fin, ratio } from "../core/util.js";
import { pct, int, count3 } from "../core/fmt.js";
import { barList } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, segmented, sourcesHtml, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";

const KIND_ZH = {
  natural: "國家公園",
  coastal: "海岸國家公園",
  monument: "歷史紀念公園",
  recreation: "風景名勝",
  university: "研究型大學",
  landmark: "文化地標",
};

export async function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const { states } = data.levels;
  const wData = await app.loadData("wonders");
  const wonders = wData?.wonders || [];
  const parks = wonders.filter((w) => w.rule === "national_park");
  const unis = wonders.filter((w) => w.rule === "research_university");
  const landmarks = wonders.filter((w) => w.rule === "landmark");

  el.insertAdjacentHTML("beforeend", tiles([
    { label: "國家公園", value: `${int(parks.length)} 座`, sub: "玉山、太魯閣、雪霸等" },
    { label: "頂尖研究型大學", value: `${int(unis.length)} 所`, sub: "台清陽交成政央山" },
    { label: "代表性地標", value: `${int(landmarks.length)} 處`, sub: "台北101、故宮、日月潭等" },
  ]));

  // --- 奇觀一覽表 ---
  const wBody = section(el, { title: "臺灣 23 座奇觀一覽", note: "游標移過可於地圖標示所在六角格，點擊直接飛至該處。可依類別篩選。" });
  let filter = "all";
  const ctl = document.createElement("div");
  ctl.className = "adv-row";
  wBody.appendChild(ctl);
  segmented(ctl, {
    label: "類別", value: filter,
    options: [
      { value: "all", label: "全部" },
      { value: "national_park", label: "國家公園" },
      { value: "research_university", label: "大學" },
      { value: "landmark", label: "地標" },
    ],
    onChange: (v) => { filter = v; updateTable(); },
  });

  const tbl = createTable(wBody, {
    caption: "臺灣奇觀清單", rank: true, maxHeight: 320, rows: wonders, search: "搜尋奇觀名稱或縣市",
    columns: [
      { key: "name", label: "名稱", align: "l", width: "minmax(0,1.5fr)", value: (r) => r.name, html: (r) => `<b>${esc(r.name)}</b>` },
      { key: "kind", label: "類型", align: "l", width: "minmax(0,1fr)", value: (r) => KIND_ZH[r.kind] || r.kind, text: (r) => KIND_ZH[r.kind] || r.kind },
      { key: "state", label: "縣市", align: "l", width: "54px", value: (r) => r.state, text: (r) => r.state || "–" },
      { key: "metric", label: "訪客／學生", width: "minmax(0,1fr)", value: (r) => r.visits ?? r.students ?? 0, text: (r) => (r.visits ? `${count3(r.visits)} 人次` : r.students ? `${int(r.students)} 人` : "–") },
    ],
    sort: { key: "metric", dir: "desc" },
    onHover: (r) => link.hover(r && r.cell >= 0 ? { cells: new Set([r.cell]), dimOthers: true, label: r.name } : null),
    onClick: (r) => {
      if (r && fin(r.x) && fin(r.y)) app.flyTo(r.x, r.y, Math.max(app.camera.scale, app.camera.fitScale * 3.5));
    },
  });
  ctx.cleanup(() => tbl.destroy());

  function updateTable() {
    tbl.setRows(filter === "all" ? wonders : wonders.filter((w) => w.rule === filter));
  }

  // --- 文教觀光產出排行 ---
  const cul = app.data.nation.yields?.find((y) => y.key === "culture");
  const cBody = section(el, { title: "各縣市文教觀光就業占比", note: `${esc(cul?.description || "教育、藝術娛樂與文化觀光服務推估就業人數。")}` });
  const cHost = document.createElement("div");
  cBody.appendChild(cHost);
  const list = topBy(states.rows, (r) => ratio(r.v.y_culture, r.v.employed), { n: 12 });
  barList(cHost, {
    rank: true, ariaLabel: "文教觀光就業占比",
    rows: list.map((x) => ({ key: x.r.key, label: x.r.name, sub: `${count3(x.r.v.y_culture)} 人`, value: x.v, text: pct(x.v), color: cul?.color, row: x.r })),
    onHover: (r) => link.hover(r ? rowsHighlight(states, [r.row]) : null),
    onClick: (r) => states.focus(r.row),
  });

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["tw_wonders", "moi_ris"], [
    "國家公園、研究型大學與代表性地標皆取自公開官方資料與台灣具代表性自然人文景點。",
  ]));

  return {};
}
