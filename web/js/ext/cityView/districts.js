// City View "Districts": the metro's real industry specialisation (districts.json, BLS QCEW) as strategy-game
// districts, plus the Encampment tier from military.json (installations + armed-forces residents).
//
//   cityDistricts(ddata, mil, id) → [district]   the metro's districts, strongest first, each with what the dock and
//                                                the map plaques need ({id, name, short, color, icon, lq, emp, …})
//   badgeOf(ddata, id) → {label, text, color, icon, district} | null | undefined   the city-type badge
//   districtsHtml(m, ddata, mil) → HTML          the section body
//   badgeHtml(m, ddata) → HTML                   the header badge
import { esc, int, pct } from "../../format.js";
import { compact, money } from "./fmt.js";
import { icon } from "../../ui/icon.js";
import { hasIcon } from "../../icons.js";

// Icons the district catalog names (d-*) are not drawn yet; until they are, a near icon from the set stands in,
// and canvas plaques without any icon get the letter in `mark`.
const FALLBACK = {
  campus: ["y-science", "🎓"], commercial_hub: ["i-finance", "💰"], industrial_zone: ["i-manufacturing", "🏭"],
  harbor: ["i-transportation", "⚓"], theater_square: ["i-arts", "🎭"], entertainment_complex: ["i-accommodation", "🎡"],
  aerodrome: ["i-transportation", "✈️"], government_plaza: ["i-public_admin", "🏛"], encampment: [null, "⛺"],
  aqueduct: ["i-utilities", "💧"],
};
const SHORT = {
  campus: "科技研發", commercial_hub: "金融商貿", industrial_zone: "製造工業", harbor: "港埠航運", theater_square: "文教觀光",
  entertainment_complex: "休閒娛樂", aerodrome: "航空運籌", government_plaza: "行政樞紐", encampment: "軍營",
  aqueduct: "農漁能源",
};
const TIER = { garrison: "駐軍", fortress: "要塞" };

const catCache = new WeakMap();
function catalog(ddata) {
  let m = catCache.get(ddata);
  if (!m) catCache.set(ddata, (m = new Map((ddata?.catalog || []).map((c) => [c.id, c]))));
  return m;
}

export function iconFor(id, cat) {
  if (cat?.icon && hasIcon(cat.icon)) return cat.icon;
  const f = FALLBACK[id]?.[0];
  return f && hasIcon(f) ? f : null;
}

const instCache = new WeakMap();
function installationsById(mil) {
  let m = instCache.get(mil);
  if (!m) instCache.set(mil, (m = new Map((mil?.installations || []).map((i) => [i.id, i]))));
  return m;
}

/**
 * The metro's districts: districts.json entries (strongest first), with military.json's Encampment merged in (its
 * tier label; added at the end when only military.json has one).
 */
export function cityDistricts(ddata, mil, id) {
  const cat = catalog(ddata);
  const row = ddata?.cities?.[id] || null;
  const mc = mil?.cities?.[id] || null;
  const out = [];
  for (const d of row?.districts || []) {
    const c = cat.get(d.id) || {};
    const spec = d.via === "specialty" && d.sub;
    out.push({
      ...d, name: c.name || d.id, color: c.color || "#5a6a7a", icon: iconFor(d.id, c), emoji: FALLBACK[d.id]?.[1] || "◆",
      cat: c, subName: d.sub ? c.sub?.[d.sub] || ddata.industries?.[d.sub]?.title || d.sub : null,
      // The map plaque: a speciality-qualified district is labelled by that speciality (its own LQ is the reason).
      short: spec ? c.sub?.[d.sub] || SHORT[d.id] : SHORT[d.id] || c.name || d.id,
      mapLq: spec ? d.sub_lq : d.lq,
      military: d.id === "encampment" ? mc : null,
    });
  }
  if (mc && !out.some((d) => d.id === "encampment")) {
    const c = cat.get("encampment") || {};
    out.push({
      id: "encampment", name: c.name || "Encampment", color: c.color || "#8a4a3a", icon: iconFor("encampment", c), emoji: "⛺",
      cat: c, lq: null, emp: null, short: TIER[mc.tier] || "Encampment", mapLq: null, military: mc, militaryOnly: true,
    });
  }
  for (const d of out) {
    if (d.military) d.tierLabel = TIER[d.military.tier] || d.military.tier;
  }
  return out;
}

/** The city-type badge; undefined while districts.json is loading, null when there is none. */
export function badgeOf(ddata, id) {
  if (!ddata) return ddata; // undefined (loading) or null (missing)
  const row = ddata.cities?.[id];
  if (!row) return null;
  if (!row.badge) return { label: "多元發展", text: "無單一產業顯著高於全臺平均。", color: "#6a7484", icon: null, district: null };
  const c = catalog(ddata).get(row.badge.district) || {};
  return { ...row.badge, color: c.color || "#6a7484", icon: iconFor(row.badge.district, c), emoji: FALLBACK[row.badge.district]?.[1] };
}

export function badgeHtml(m, ddata) {
  const b = badgeOf(ddata, m.city.id);
  if (!b) return "";
  return `<span class="cv-type${b.district ? "" : " plain"}" style="--tc:${esc(b.color)}" title="城市定位：${esc(b.text || b.label)}（${esc(String(ddata.year || ""))}）">
    <span class="cv-type-ic">${icon(b.icon, b.emoji || "◆", { size: 13 })}</span>${esc(b.label)}</span>`;
}

const ge = (lb) => (lb ? "≥" : "");
const signed = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)}%`);

function lqTag(lq, lb, tip) {
  if (lq == null) return "";
  const cls = lq >= 1.25 ? "hi" : lq <= 0.75 ? "lo" : "mid";
  return `<span class="cv-lq ${cls}" title="${esc(tip || `區位商數：為全臺平均就業占比的 ${lq.toFixed(2)} 倍`)}">×${ge(lb)}${lq.toFixed(1)}</span>`;
}

function districtCard(d, row, ddata, mil) {
  const nat = ddata?.national || {};
  const c = d.cat || {};
  const lb = !!d.lower_bound;
  const supTip = lb ? ` 部分鄉鎮資料未公開，數值為下限。` : "";
  const facts = [];
  if (d.emp != null) {
    facts.push(`<div><span>就業人數</span><b>${ge(lb)}${compact(d.emp)}</b><small>${d.share != null ? `占縣市 ${pct(d.share, 1)}` : ""}</small></div>`);
  }
  if (d.avg_pay != null) {
    facts.push(`<div><span>平均所得</span><b>${money(d.avg_pay)}</b><small>${row?.avg_pay != null ? `縣市 ${money(row.avg_pay)}` : ""}</small></div>`);
  }
  if (d.strength != null) {
    facts.push(`<div title="高於全臺平均結構之超額就業人數"><span>超額聚集</span><b>${ge(lb)}${compact(Math.max(0, d.strength))}</b><small>人</small></div>`);
  }
  let spec = "";
  if (d.sub && d.subName) {
    const slb = d.sub_lower_bound ?? !!(row?.top || []).find((t) => t.naics === d.sub)?.lower_bound;
    spec = `<p class="cv-dc-sub">核心專精：<b>${esc(d.subName)}</b> ${lqTag(d.sub_lq, slb)}${
      d.sub_emp != null ? ` <small>${ge(slb)}${compact(d.sub_emp)} 人</small>` : ""}${
      d.note ? `<br><small>${esc(d.note)}</small>` : ""}</p>`;
  }
  let milHtml = "";
  if (d.military) {
    const mc = d.military;
    const inst = installationsById(mil);
    const names = (mc.installations || []).map((i) => inst.get(i)?.name).filter(Boolean);
    milHtml = `<div class="cv-dc-mil">
      <p><b>${esc(d.tierLabel)}</b>${mc.naval ? " (naval)" : ""}: ${int(mc.armed_forces)} residents in the armed forces, ${pct(mc.share, mc.share < 0.01 ? 2 : 1)} of people 16 and over.</p>
      ${names.length ? `<p class="cv-dc-inst">${names.slice(0, 5).map((n) => `<span>${esc(n)}</span>`).join("")}${
        mc.installation_count > Math.min(5, names.length) ? `<small>+${mc.installation_count - Math.min(5, names.length)} more</small>` : ""}</p>` : ""}
    </div>`;
  }
  const caveat = c.caveat ? `<p class="cv-dc-cav">${esc(c.caveat)}</p>` : "";
  const title = d.militaryOnly ? `${esc(d.name)} · ${esc(d.tierLabel)}` : d.military ? `${esc(d.name)} · ${esc(d.tierLabel)}` : esc(d.name);
  return `<div class="cv-dc" style="--dc:${esc(d.color)}" title="${esc(c.description || "")}${esc(supTip)}">
    <div class="cv-dc-h"><span class="cv-dc-hex">${icon(d.icon, d.emoji, { size: 18 })}</span>
      <div class="cv-dc-t"><b>${title}</b><small>${esc(c.description || "")}</small></div>
      ${d.lq != null ? lqTag(d.lq, lb, `Location quotient: the metro's share of jobs in these industries is ${d.lq.toFixed(2)}× the national share.${supTip}`) : ""}</div>
    ${facts.length ? `<div class="cv-dc-f">${facts.join("")}</div>` : ""}
    ${spec}${milHtml}${caveat}
  </div>`;
}

function topTable(row, ddata) {
  const top = row?.top || [];
  if (!top.length) return "";
  const max = Math.max(...top.map((t) => t.lq || 0), 1);
  return `<h4 class="cv-h4">最專精產業排行 <span class="muted">依區位商數（LQ）</span></h4>
  <div class="cv-top" role="table" aria-label="最專精產業排行">
    <div class="cv-top-r cv-top-hd" role="row"><span role="columnheader">產業</span><span role="columnheader">就業</span><span role="columnheader">×全臺</span><span role="columnheader">所得</span><span role="columnheader">年變</span></div>
    ${top.map((t) => {
      const title = ddata.industries?.[t.naics]?.title || t.naics;
      const lb = !!t.lower_bound;
      return `<div class="cv-top-r" role="row" title="${esc(title)}">
        <span role="cell" class="cv-top-n">${esc(title)}<i style="width:${((Math.log(1 + (t.lq || 0)) / Math.log(1 + max)) * 100).toFixed(1)}%"></i></span>
        <span role="cell">${ge(lb)}${compact(t.emp)}</span>
        <span role="cell"><b>${t.lq != null ? `${ge(lb)}${t.lq.toFixed(1)}` : "–"}</b></span>
        <span role="cell">${money(t.avg_pay)}</span>
        <span role="cell" class="${t.oty_pct == null ? "" : t.oty_pct >= 0 ? "good" : "bad"}">${signed(t.oty_pct)}</span></div>`;
    }).join("")}
  </div>`;
}

/** The Districts section body. ddata: districts.json (undefined while loading, null when missing). */
export function districtsHtml(m, ddata, mil) {
  if (ddata === undefined) return `<p class="muted cv-note">載入產業分區資料中…</p>`;
  if (!ddata) return `<p class="muted cv-note">尚未提供產業分區資料。</p>`;
  const id = m.city.id;
  const row = ddata.cities?.[id] || null;
  const list = cityDistricts(ddata, mil, id);
  const b = badgeOf(ddata, id);
  let lead;
  if (!row) {
    lead = `<p class="cv-lead">${esc(m.city.name)}尚無產業分區統計資料。</p>`;
  } else {
    const cnt = row.counties ? `（涵蓋 ${row.counties[0]} 個鄉鎮市區）` : "";
    lead = `<p class="cv-lead">${b?.district ? `<b class="cv-type-l" style="--tc:${esc(b.color)}">${esc(b.label)}</b> · ${esc(b.text || "")}。` : ""}就業規模約 ${
      int(row.emp)} 人${esc(cnt)}，家庭平均可支配所得 ${money(row.avg_pay)}（全臺加權平均 ${money(ddata.national?.avg_pay)}）。</p>`;
  }
  const cards = list.length
    ? `<div class="cv-dcs">${list.map((d) => districtCard(d, row, ddata, mil)).join("")}</div>`
    : row ? `<p class="muted cv-note">無單一產業分區超過門檻：就業結構接近全臺平均。</p>` : "";
  return `${lead}
    ${cards}
    ${topTable(row, ddata)}
    <div class="cv-schematic">
      <p><b>◆ 地圖分區標記</b>會顯示於城市周邊六角格上，為示意位置，代表該縣市的代表性產業強項。</p>
    </div>
    <details class="cv-more cv-rule"><summary>產業分區評定方式</summary>
      <p>${esc(ddata.rule?.text || "")}</p>
    </details>
    <p class="cv-note">${esc(ddata.vintage || "")}。×N 代表該產業就業占比為全臺平均的 N 倍（區位商數 LQ）。</p>`;
}
