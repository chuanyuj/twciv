// The Almanac: what every number means and exactly where it comes from.
import { resolveTables } from "../terrain.js";
import { esc } from "../format.js";
import { parseHex, luminance } from "../color.js";
import { icon, glyph } from "./icon.js";

const COVER_ICON = { forest_deciduous: "l-forest", forest_evergreen: "l-forest", forest_mixed: "l-forest", cropland: "l-farmland", pasture: "l-farmland", urban: "l-developed" };
// Glyph colour that reads on a resource medallion (dark on light faces such as nuclear yellow or silver).
const inkOn = (hex) => {
  try { return /^#[0-9a-f]{6}$/i.test(hex || "") && luminance(parseHex(hex)) > 0.4 ? "#1c1710" : "#f8f0d8"; } catch { return "#f8f0d8"; }
};
const CATEGORY = { energy: "能源與發電廠", mineral: "礦產", agri: "農漁業" };

export function initPedia(data) {
  const modal = document.getElementById("pedia");
  const card = modal.querySelector(".modal-card");
  const nav = document.getElementById("pedia-nav");
  const body = document.getElementById("pedia-body");
  const srcName = (id) => data.sources?.find((s) => s.id === id)?.title || id || "";
  let restoreFocus = null;

  const h2 = (ic, fb, text) => `<h2>${icon(ic, fb, { size: 24 })}<span>${esc(text)}</span></h2>`;

  const pages = {
    "關於本地圖": () => `
      ${h2("pedia", "📖", "關於臺灣文明地圖")}
      <p>這是以 4X 策略遊戲地圖風格呈現的真實臺灣。地圖上每一個六角格、縣市與鄉鎮市區數據皆來自公開政府資料與地球觀測資料，完整清單請見<i>資料來源</i>。</p>
      <h4>建構方式</h4>
      <p>採用以臺灣為中心（121°E, 23.7°N）的等面積投影，切分為 ${data.world.grid.cols}×${data.world.grid.rows} 個六角格（每格半徑約 3.5 公里），涵蓋臺灣本島、澎湖、金門與馬祖全數 22 縣市與 368 鄉鎮市區。地形與水深來自 NOAA ETOPO1 1 弧分高程資料。</p>
      <h4>操作提示</h4>
      <p>拖曳或方向鍵／WASD 平移 · 滾輪、+/– 或雙擊縮放 · 點擊城市橫幅或陸地開啟縣市面板 · / 或 ⌘K 搜尋 · L 切換濾鏡 · R 顯示／隱藏電廠 · ? 查看快捷鍵 · Esc 關閉面板。</p>`,
    "五大產出": () => `
      ${h2("y-production", "⚙️", "五大產出")}
      <p>將策略遊戲的五大產出對應到真實臺灣指標：農漁糧食、工業製造、科技研發與文教觀光為各業推估就業人數；<b>經濟產值</b>採用財政部各縣市營利事業全年銷售額（因主計總處僅編布全國 GDP 而無縣市 GDP）。</p>
      <table>${data.nation.yields.map((y) => `<tr><td class="ic" style="color:${esc(y.color)}">${glyph(y, 26)}</td><td><b style="color:${esc(y.color)}">${esc(y.label)}</b><br>${esc(y.description)}</td></tr>`).join("")}</table>`,
    "各縣市": () => `
      ${h2("terrain", "🗺️", "臺灣 22 縣市")}
      <p>點擊任一縣市陸地即可開啟縣市面板，查看該縣市在全台 22 縣市中的產出排名、人口變化、每戶可支配所得、房價所得比與產業結構（${esc(data.nation.vintage)}${data.nation.gdp_vintage ? `；${esc(data.nation.gdp_vintage)}` : ""}）。</p>`,
    "地形與水深": () => {
      const t = data.w?.tables || resolveTables(data.world.tables);
      const hasCover = Array.isArray(data.world.cover);
      const row = (x) => `<tr><td class="nm">${x.color ? `<span class="swatch" style="background:${esc(x.color)}"></span>` : ""}${
        COVER_ICON[x.key] ? icon(COVER_ICON[x.key], "", { size: 15 }) + " " : ""}<b>${esc(x.name)}</b></td><td>${esc(x.rule || "")}</td></tr>`;
      return `
      ${h2("terrain", "🗺️", "地形與水深")}
      <p>每個六角格彙整 NOAA ETOPO1（約 1.8 公里解析度）海拔與水深樣本，忠實呈現中央山脈百岳高山、西部平原、淺海臺灣海峽與深邃太平洋的對比。</p>
      <h4>${icon("l-forest", "🌲", { size: 16 })} 地表覆蓋</h4>
      ${hasCover ? `<table>${t.cover.filter((x) => x.id > 0).map(row).join("")}</table>` : ""}
      <h4>地形起伏</h4>
      <table>${t.relief.map(row).join("")}</table>
      <h4>${icon("r-hydro", "💧", { size: 16 })} 海域</h4>
      <table>${t.water.filter((x) => x.id > 0).map(row).join("")}</table>`;
    },
    "地圖濾鏡": () => `
      ${h2("layers", "▤", "地圖濾鏡")}
      <p>濾鏡以 368 鄉鎮市區或 22 縣市資料重新著色地圖（${esc(data.lenses.vintage)}）。游標移過或拖曳下方圖例色帶，可即時高亮特定數值區間。</p>
      ${(data.lenses.groups || [{ id: null, name: "" }]).map((g) => {
        const ls = data.lenses.lenses.filter((l) => !g.id || l.group === g.id);
        if (!ls.length) return "";
        return `${g.name ? `<h3 class="grp">${icon(`g-${g.id}`, "", { size: 16 })} ${esc(g.name)}</h3>` : ""}${ls.map((l) => `
          <div class="lens-entry"><div class="le-ic">${glyph(l, 26)}</div><div>
          <h4>${esc(l.name)}</h4><p>${esc(l.description)}<br>
          <i class="le-ramp" style="background:linear-gradient(90deg, ${(l.ramp || []).map(esc).join(",")})"></i>
          <span class="muted">範圍：${l.domain[0].toLocaleString()}–${l.domain[1].toLocaleString()} ${esc(l.unit)}${l.source ? " · " + esc(srcName(l.source)) : ""}</span></p></div></div>`).join("")}`;
      }).join("")}`,
    "電廠資源": () => {
      const r = data.resources;
      if (!r?.types?.length) return `${h2("resources", "⛏️", "電廠資源")}<p class="muted">尚未收錄資源資料。</p>`;
      const count = new Map();
      for (const it of r.items || []) count.set(it.type, (count.get(it.type) || 0) + 1);
      const cats = [...new Set(r.types.map((t) => t.category || "other"))];
      return `
      ${h2("resources", "⛏️", "電廠資源")}
      <p>標示台灣主要核能、燃氣、燃煤、水力、抽蓄水力、離岸風電、太陽光電與地熱發電廠位置與裝置容量（MW）。按 <b>R</b> 可隨時顯示或隱藏。</p>
      ${cats.map((c) => `<h4>${esc(CATEGORY[c] || c)}</h4><table class="res-table">
        <tr><th></th><th>類型</th><th>說明</th><th>座數</th></tr>
        ${r.types.filter((t) => (t.category || "other") === c).map((t) => `<tr>
          <td class="ic"><span class="res-ic" style="background:${esc(t.color || "#24384f")};color:${inkOn(t.color)}">${glyph(t, 20)}</span></td>
          <td class="nm"><b>${esc(t.name)}</b>${t.unit ? `<br><span class="muted">單位：${esc(t.unit)}</span>` : ""}</td>
          <td>${esc(t.description || "")}<br><span class="muted">來源：${esc(srcName(t.source))}</span></td>
          <td class="num">${count.get(t.id) || 0}</td></tr>`).join("")}</table>`).join("")}`;
    },
    "資料來源": () => `
      ${h2("pedia", "📖", "資料來源")}
      ${data.sources.map((s) => `
        <h4>${esc(s.title)}</h4>
        <p>${esc(s.description)}<br>
        <span class="muted">${esc(s.publisher)} · ${esc(s.license)}${s.vintage ? " · " + esc(s.vintage) : ""} ·
        <a href="${esc(s.homepage)}" target="_blank" rel="noopener">官方網站</a></span></p>`).join("")}`,
  };

  const show = (name) => {
    if (!pages[name]) name = "關於本地圖";
    body.innerHTML = pages[name]();
    body.scrollTop = 0;
    nav.querySelectorAll("button").forEach((b) => {
      const on = b.dataset.page === name;
      b.classList.toggle("active", on);
      b.setAttribute("aria-current", on ? "page" : "false");
    });
  };
  nav.innerHTML = `<div class="hd">資料年鑑</div>` + Object.keys(pages).map((p) => `<button data-page="${esc(p)}">${esc(p)}</button>`).join("");
  nav.onclick = (e) => {
    const b = e.target.closest("button[data-page]");
    if (b) show(b.dataset.page);
  };
  const close = () => {
    if (modal.hidden) return;
    modal.hidden = true;
    if (restoreFocus && document.contains(restoreFocus)) restoreFocus.focus();
    restoreFocus = null;
  };
  modal.onclick = (e) => {
    if (e.target === modal || e.target.closest("[data-close]")) close();
  };
  // Keep Tab inside the dialog.
  modal.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = [...card.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")].filter((x) => x.offsetParent);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  return {
    open(page = "About this map") {
      if (modal.hidden) restoreFocus = document.activeElement;
      show(page);
      modal.hidden = false;
      (nav.querySelector("button.active") || card.querySelector("[data-close]"))?.focus();
    },
    close,
    get isOpen() {
      return !modal.hidden;
    },
  };
}
