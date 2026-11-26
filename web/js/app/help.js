// Keyboard & mouse cheat-sheet.
import { icon } from "../ui/icon.js";

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
const MOD = isMac ? "⌘" : "Ctrl";

const ROWS = [
  ["移動與縮放", [
    [["拖曳", "←↑→↓", "WASD"], "平移地圖"],
    [["滾輪", "+", "–"], "放大與縮小"],
    [["雙擊"], "放大檢視該處"],
    [["雙指"], "觸控縮放與平移"],
    [["小地圖"], "點擊或拖曳快速跳轉"],
  ]],
  ["探索臺灣", [
    [["點擊城市橫幅"], "開啟該縣市城市視角與市民結構"],
    [["點擊陸地"], "開啟該縣市統計面板"],
    [["/", `${MOD} K`], "搜尋 22 縣市與 368 鄉鎮市區"],
    [["L", "Shift L"], "切換下一個／上一個地圖濾鏡"],
    [["圖例色帶"], "游標移過或拖曳區間以高亮篩選"],
    [["R"], "顯示或隱藏發電廠資源圖示"],
  ]],
  ["面板與快捷鍵", [
    [["?"], "開啟本操作說明"],
    [["Esc"], "依序關閉說明、搜尋、資料年鑑與面板"],
  ]],
];

export function initHelp() {
  const modal = document.getElementById("help");
  if (!modal) return { open() {}, close() {}, get isOpen() { return false; } };
  const card = modal.querySelector(".help-card");
  let restore = null;
  card.innerHTML = `
    <button class="icon-btn help-close" data-close aria-label="關閉說明">${icon("close", "✕", { size: 13 })}</button>
    <h2 id="help-title">${icon("help", "?", { size: 22 })}<span>操作說明</span></h2>
    <div class="help-cols">${ROWS.map(([title, rows]) => `
      <section><h3>${title}</h3>${rows.map(([keys, what]) => `
        <div class="help-row"><span class="keys">${keys.map((k) => `<kbd>${k}</kbd>`).join("")}</span><span>${what}</span></div>`).join("")}
      </section>`).join("")}</div>
    <p class="help-foot">所有數據皆取自公開政府資料（內政部戶政司、主計總處、財政部、台電、NOAA ETOPO1 等），請點選上方<b>資料年鑑</b>查閱完整出處與資料口徑。網址列連結會自動保存目前的視角與濾鏡狀態。</p>`;

  const close = () => {
    if (modal.hidden) return;
    modal.hidden = true;
    if (restore && document.contains(restore)) restore.focus();
    restore = null;
  };
  modal.addEventListener("click", (e) => {
    if (e.target === modal || e.target.closest("[data-close]")) close();
  });
  modal.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault(); // the only focusable control is the close button
    card.querySelector("[data-close]").focus();
  });

  return {
    open() {
      if (!modal.hidden) return;
      restore = document.activeElement;
      modal.hidden = false;
      card.querySelector("[data-close]").focus();
    },
    close,
    toggle() { modal.hidden ? this.open() : close(); },
    get isOpen() { return !modal.hidden; },
  };
}
