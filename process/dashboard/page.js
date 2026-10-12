const D = JSON.parse(document.getElementById("data").textContent);
const ICONS = JSON.parse(document.getElementById("icons").textContent);
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US"));
const pct = (n) => (n === null || n === undefined ? "—" : n > 0 && n < 0.01 ? "<1%" : `${Math.round(n * 100)}%`);
const svg = (name, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

function paintIcons(root = document) {
  for (const el of root.querySelectorAll("[data-icon]")) {
    el.innerHTML = svg(el.dataset.icon, Number(el.dataset.size) || 16);
  }
}

const TERRITORY = {
  open: ["badge-good", "Open territory"],
  near: ["badge-warn", "Stockist nearby"],
  unknown: ["badge-neutral", "Location unknown"],
};
const SURVEY = {
  full: ["badge-good", "Full list"],
  area: ["badge-warn", "Area search only"],
  robots: ["badge-bad", "robots.txt disallows"],
  own: ["badge-neutral", "Own shops only"],
  none: ["badge-neutral", "No list"],
};
const GROUPS = [
  ["same", "Same store as a stockist"],
  ["check", "Same name, to check by hand"],
  ["near", "Not ours, stockist nearby"],
  ["open", "Not ours, open territory"],
];
const badge = ([cls, text]) => `<span class="badge ${cls}">${esc(text)}</span>`;
const brandName = Object.fromEntries(D.watched.map((w) => [w.key, w.brand]));

// Shell: theme, sidebar

const themeButton = $("#theme");
themeButton.addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme !== "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  themeButton.setAttribute("aria-checked", String(dark));
  $("#theme-label").textContent = dark ? "DARK" : "LIGHT";
});

function setDrawer(open) {
  $("#sidebar").classList.toggle("open", open);
  $("#scrim").hidden = !open;
}
$("#menu-toggle").addEventListener("click", () => {
  if (window.matchMedia("(max-width: 860px)").matches) setDrawer(!$("#sidebar").classList.contains("open"));
  else $("#shell").classList.toggle("collapsed");
});
$("#scrim").addEventListener("click", () => setDrawer(false));
for (const a of document.querySelectorAll(".sidebar a")) a.addEventListener("click", (e) => e.preventDefault());

// Head, tiles, footer

const t = D.watched_territory;
$("#lede").innerHTML =
  `Where brands like ours are sold, read from the catalogues of the stores in one run: ` +
  `${num(D.readable)} of ${num(D.stores)} stores were readable.`;
$("#run-chip").innerHTML = `<span class="muted">Run</span> 9 Oct 2026 · ${esc(D.run_id.slice(-6))}`;

const tiles = [
  ["Stores read", num(D.readable), `of ${num(D.stores)} in the run · ${num(D.stores - D.readable)} not read`],
  [
    "Carry a watched brand",
    num(D.watched_stores),
    D.watched.map((w) => `${w.brand} ${w.stores}`).join(" · "),
  ],
  [
    "Of those, not yet ours",
    num(D.watched_not_ours),
    `${num(D.watched_email)} with an email address · ${num(D.watched_customers)} already stockists`,
  ],
  [
    "In open territory",
    num(t.open ?? 0),
    `No stockist within ${num(D.radius_miles)} miles · ${num(t.near ?? 0)} near one · ${num(t.unknown ?? 0)} location unknown`,
  ],
];
$("#stats").innerHTML = tiles
  .map(([label, value, sub]) => `<div class="stat"><dt>${esc(label)}</dt><dd>${value}</dd><p class="sub">${esc(sub)}</p></div>`)
  .join("");

$("#limits").innerHTML =
  `${num(D.stores - D.readable)} of the ${num(D.stores)} stores in this run could not be read. They are unknown, ` +
  `not irrelevant. A brand's count is the number of read stores that sell it, so it cannot be read as a share of ` +
  `that brand's retailers. "Ours" is measured against the stockist list only, until an account export is added. ` +
  `${num(D.opportunities.length - D.located)} of ${num(D.opportunities.length)} stores have no known location.`;

// Tables: one helper for a sortable, paged table

function sortRows(rows, sort) {
  if (!sort.key) return rows;
  const value = (r) => (typeof sort.key === "function" ? sort.key(r) : r[sort.key]);
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * sort.dir;
  });
}

function tableHtml(columns, rows, sort) {
  const head = columns
    .map((c, i) => {
      const cls = c.num ? ' class="num"' : "";
      if (!c.sort) return `<th${cls}>${esc(c.label)}</th>`;
      const active = sort.col === i;
      const aria = active ? ` aria-sort="${sort.dir < 0 ? "descending" : "ascending"}"` : "";
      const arrow = active ? (sort.dir < 0 ? " ↓" : " ↑") : "";
      return `<th${cls}${aria}><button type="button" data-sort="${i}">${esc(c.label)}${arrow}</button></th>`;
    })
    .join("");
  const body = rows
    .map((r) => `<tr>${columns.map((c) => `<td class="${c.num ? "num" : ""} ${c.wrap ? "rm-wrap" : ""}">${c.cell(r)}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="table-wrap"><table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

const bar = (value, max, quiet = false) =>
  `<span class="rm-bar" title="${num(value)}"><span class="share-track" aria-hidden="true"><span class="share-fill ${quiet ? "rm-quiet" : ""}" style="width:${max ? (100 * value) / max : 0}%"></span></span><span class="num">${num(value)}</span></span>`;

const segmented = (name, options, current) =>
  `<div class="segmented" role="tablist" aria-label="${esc(name)}">${options
    .map(([key, label, count]) => `<button type="button" role="tab" data-${name}="${esc(key)}" aria-selected="${key === current}">${esc(label)}${count === undefined ? "" : ` · ${num(count)}`}</button>`)
    .join("")}</div>`;

const PAGE = 15;

// Opportunities

const opp = { brand: "watched", territory: "all", email: false, q: "", sort: { col: null, key: null, dir: -1 }, page: 0 };

const OPP_COLUMNS = [
  {
    label: "Store",
    cell: (r) =>
      `<a href="https://${esc(r.domain)}" target="_blank" rel="noreferrer">${esc(r.name || r.domain)}</a>` +
      `<span class="sub">${esc([r.city, r.state].filter(Boolean).join(", ") || "location unknown")}</span>`,
  },
  {
    label: "Watched brands",
    wrap: true,
    sort: (r) => r.watched.length,
    cell: (r) =>
      r.watched.length
        ? `<span class="rm-tags">${r.watched.map((k) => `<span class="tag solid">${esc(brandName[k])}</span>`).join("")}</span>`
        : `<span class="muted">—</span>`,
  },
  {
    label: "Other relevant brands",
    sort: (r) => r.relevant.length,
    cell: (r) =>
      r.relevant.length
        ? `<span title="${esc(r.relevant.join(", "))}">${esc(r.relevant.slice(0, 2).join(", "))}${r.relevant.length > 2 ? ` <span class="muted">+${r.relevant.length - 2}</span>` : ""}</span>`
        : `<span class="muted">—</span>`,
  },
  { label: "Knit products", num: true, sort: "knit", cell: (r) => num(r.knit) },
  {
    label: "Knit median",
    num: true,
    cell: (r) => (r.price === null ? "—" : `${num(Math.round(r.price))} ${esc(r.currency || "")}`),
  },
  {
    label: "Territory",
    sort: "miles",
    cell: (r) =>
      badge(TERRITORY[r.territory]) +
      (r.miles === null ? "" : `<span class="sub">nearest stockist ${r.miles.toFixed(1)} mi</span>`),
  },
  { label: "Email", cell: (r) => (r.email ? "Yes" : `<span class="muted">—</span>`) },
  { label: "Store score", num: true, sort: "score", cell: (r) => num(r.score) },
];

function oppRows() {
  const q = opp.q.trim().toLowerCase();
  return D.opportunities.filter(
    (r) =>
      (opp.brand === "all" || (opp.brand === "watched" ? r.watched.length > 0 : r.watched.includes(opp.brand))) &&
      (opp.territory === "all" || r.territory === opp.territory) &&
      (!opp.email || r.email) &&
      (!q ||
        [r.domain, r.name, r.city, r.state, ...r.relevant, ...r.watched.map((k) => brandName[k])]
          .filter(Boolean)
          .some((v) => v.toLowerCase().includes(q))),
  );
}

function renderOpp(keepFocus = false) {
  const all = D.opportunities;
  const brands = [
    ["watched", "Any watched brand", all.filter((r) => r.watched.length).length],
    ...D.watched.map((w) => [w.key, w.brand, all.filter((r) => r.watched.includes(w.key)).length]),
    ["all", "All candidates", all.length],
  ];
  const rows = sortRows(oppRows(), opp.sort);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  opp.page = Math.min(opp.page, pages - 1);
  const shown = rows.slice(opp.page * PAGE, (opp.page + 1) * PAGE);
  $("#panel").innerHTML = `
    <section class="card" aria-label="Stores to approach">
      <div class="card-head">
        <h2>Stores to approach</h2>
        <span class="muted small">retail partner candidates that are not stockists</span>
        <p>Each store was read by the bot and sells the brands shown. Sorted as ranked by the notebook; click a column to re-sort (Territory sorts by distance to the nearest stockist).</p>
      </div>
      <div class="rm-filters">
        ${segmented("brand", brands, opp.brand)}
        ${segmented("territory", [["all", "Any territory"], ["open", "Open"], ["near", "Stockist nearby"], ["unknown", "Unknown"]], opp.territory)}
        <label class="rm-check"><input type="checkbox" id="opp-email" ${opp.email ? "checked" : ""} /> Has an email</label>
        <div class="search">${svg("search", 15)}<input type="search" id="opp-q" placeholder="Store, city or brand" aria-label="Search stores" value="${esc(opp.q)}" /></div>
      </div>
      ${rows.length ? tableHtml(OPP_COLUMNS, shown, opp.sort) : `<p class="empty">No store matches these filters.</p>`}
      <div class="pager">
        <span>${rows.length ? `${opp.page * PAGE + 1}–${opp.page * PAGE + shown.length} of ${num(rows.length)} stores` : "0 stores"}</span>
        <button type="button" class="button ghost small-button" id="opp-prev" ${opp.page === 0 ? "disabled" : ""}>Previous</button>
        <button type="button" class="button ghost small-button" id="opp-next" ${opp.page >= pages - 1 ? "disabled" : ""}>Next</button>
      </div>
    </section>`;
  const panel = $("#panel");
  for (const b of panel.querySelectorAll("[data-brand]")) b.addEventListener("click", () => ((opp.brand = b.dataset.brand), (opp.page = 0), renderOpp()));
  for (const b of panel.querySelectorAll("[data-territory]"))
    b.addEventListener("click", () => ((opp.territory = b.dataset.territory), (opp.page = 0), renderOpp()));
  $("#opp-email").addEventListener("change", (e) => ((opp.email = e.target.checked), (opp.page = 0), renderOpp()));
  $("#opp-q").addEventListener("input", (e) => ((opp.q = e.target.value), (opp.page = 0), renderOpp(true)));
  $("#opp-prev").addEventListener("click", () => (opp.page--, renderOpp()));
  $("#opp-next").addEventListener("click", () => (opp.page++, renderOpp()));
  bindSort(panel, OPP_COLUMNS, opp, renderOpp);
  if (keepFocus) {
    const input = $("#opp-q");
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
}

function bindSort(root, columns, state, render) {
  for (const b of root.querySelectorAll("[data-sort]")) {
    b.addEventListener("click", () => {
      const col = Number(b.dataset.sort);
      state.sort = { col, key: columns[col].sort, dir: state.sort.col === col ? -state.sort.dir : -1 };
      state.page = 0;
      render();
    });
  }
}

// Brands

const br = { kind: "all", sort: { col: null, key: null, dir: -1 }, page: 0 };
const maxStores = Math.max(...D.brands.map((b) => b.stores));

const BRAND_COLUMNS = [
  {
    label: "Brand",
    wrap: true,
    cell: (b) => `<span class="rm-brand">${esc(b.brand)}${b.watched ? ` <span class="tag solid">Watched</span>` : ""}</span>`,
  },
  { label: "Type", cell: (b) => `<span class="tag">${b.kind === "rival" ? "Knitwear rival" : "Marker brand"}</span>` },
  { label: "Stores selling it", sort: "stores", cell: (b) => bar(b.stores, maxStores) },
  { label: "Also ours", num: true, sort: "shared", cell: (b) => num(b.shared) },
  { label: "Not ours", num: true, sort: "not_ours", cell: (b) => num(b.not_ours) },
  { label: "In open territory", num: true, sort: "open", cell: (b) => num(b.open) },
  { label: "Knitwear share", num: true, sort: "knit_share", cell: (b) => pct(b.knit_share) },
  { label: "Price vs ours", num: true, sort: "price", cell: (b) => (b.price === null ? "—" : `${b.price.toFixed(2)}×`) },
  { label: "Relevance", num: true, sort: "rank", cell: (b) => (b.rank === null ? "—" : b.rank.toFixed(2)) },
  {
    label: "Coverage",
    cell: (b) => badge(b.full ? ["badge-good", "Sample + full list"] : ["badge-neutral", "Sample"]),
  },
];

function renderBrands() {
  const kinds = [
    ["all", "All brands", D.brands.length],
    ["watched", "Watched", D.brands.filter((b) => b.watched).length],
    ["rival", "Knitwear rivals", D.brands.filter((b) => b.kind === "rival").length],
    ["marker", "Marker brands", D.brands.filter((b) => b.kind === "marker").length],
  ];
  const rows = sortRows(
    D.brands.filter((b) => br.kind === "all" || (br.kind === "watched" ? b.watched : b.kind === br.kind)),
    br.sort,
  );
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  br.page = Math.min(br.page, pages - 1);
  const shown = rows.slice(br.page * PAGE, (br.page + 1) * PAGE);
  $("#panel").innerHTML = `
    <section class="card" aria-label="Brands">
      <div class="card-head">
        <h2>Brands, by closeness to ours</h2>
        <span class="muted small">brands with enough read stores to be ranked</span>
        <p>A knitwear rival holds mostly knitwear. A marker brand holds little, but shows the kind of boutique that suits us. Price vs ours compares knitwear prices in US dollars: 1.00× is the same.</p>
      </div>
      <div class="rm-filters">${segmented("kind", kinds, br.kind)}</div>
      ${tableHtml(BRAND_COLUMNS, shown, br.sort)}
      <div class="pager">
        <span>${br.page * PAGE + 1}–${br.page * PAGE + shown.length} of ${num(rows.length)} brands</span>
        <button type="button" class="button ghost small-button" id="br-prev" ${br.page === 0 ? "disabled" : ""}>Previous</button>
        <button type="button" class="button ghost small-button" id="br-next" ${br.page >= pages - 1 ? "disabled" : ""}>Next</button>
      </div>
    </section>`;
  const panel = $("#panel");
  for (const b of panel.querySelectorAll("[data-kind]")) b.addEventListener("click", () => ((br.kind = b.dataset.kind), (br.page = 0), renderBrands()));
  $("#br-prev").addEventListener("click", () => (br.page--, renderBrands()));
  $("#br-next").addEventListener("click", () => (br.page++, renderBrands()));
  bindSort(panel, BRAND_COLUMNS, br, renderBrands);
}

// Regions

const rg = { sort: { col: null, key: null, dir: -1 }, page: 0 };
const regionMax = Math.max(...D.regions.flatMap((r) => [r.opportunities, r.stockists]));
const REGION_COLUMNS = [
  { label: "State or province", sort: "state", cell: (r) => `<strong>${esc(r.state)}</strong>` },
  { label: "Stores to approach", sort: "opportunities", cell: (r) => bar(r.opportunities, regionMax) },
  { label: "Of those, in open territory", num: true, sort: "open_territory", cell: (r) => num(r.open_territory) },
  { label: "Our stockists", sort: "stockists", cell: (r) => bar(r.stockists, regionMax, true) },
];

function renderRegions() {
  $("#panel").innerHTML = `
    <section class="card" aria-label="Regions">
      <div class="card-head">
        <h2>Where the stores are, against our stockists</h2>
        <span class="muted small">${num(D.located)} of ${num(D.opportunities.length)} candidate stores have a known location</span>
        <p>Both bars count stores on the same scale. A long first bar beside a short second one is a region where similar brands sell and we are thin.</p>
      </div>
      ${tableHtml(REGION_COLUMNS, sortRows(D.regions, rg.sort), rg.sort)}
    </section>`;
  bindSort($("#panel"), REGION_COLUMNS, rg, renderRegions);
}

// Published lists

function renderLists() {
  const L = D.locator ?? { brand: "", total: 0, groups: {}, states: [] };
  const top = Math.max(1, ...GROUPS.map(([k]) => L.groups[k] ?? 0));
  const stateMax = Math.max(...L.states.flatMap((s) => [s.brand_retailers, s.stockists]));
  const states = L.states.slice(0, 12);
  $("#panel").innerHTML = `
    <div class="rm-split">
      <section class="card" aria-label="Store locator survey">
        <div class="card-head">
          <h2>Which brands publish their retailers</h2>
                    <p>A list is read only when the host that serves it allows crawlers and gives the whole list in one request.</p>
        </div>
        ${tableHtml(
          [
            { label: "Brand", cell: (s) => `<strong>${esc(s.brand)}</strong>` },
            { label: "Locator", cell: (s) => esc(s.locator) },
            { label: "Status", cell: (s) => badge(SURVEY[s.status]) },
            { label: "Locations", num: true, cell: (s) => num(s.locations) },
          ],
          D.survey,
          {},
        )}
      </section>
      <section class="card" aria-label="${esc(L.brand)} published list">
        <div class="card-head">
          <h2>${esc(L.brand)}: ${num(L.total)} published retailers</h2>
          <span class="muted small">full list, matched by name and place</span>
        </div>
        <ul class="share-list rm-share">
          ${GROUPS.map(
            ([k, label]) =>
              `<li><span>${esc(label)}</span><span class="share-track" aria-hidden="true"><span class="share-fill" style="width:${(100 * (L.groups[k] ?? 0)) / top}%"></span></span><span class="num">${num(L.groups[k] ?? 0)} · ${pct((L.groups[k] ?? 0) / L.total)}</span></li>`,
          ).join("")}
        </ul>
      </section>
    </div>
    <section class="card" aria-label="${esc(L.brand)} retailers by state">
      <div class="card-head">
        <h2>${esc(L.brand)} retailers against our stockists, by state</h2>
        <span class="muted small">12 widest gaps of ${num(L.states.length)} states</span>
      </div>
      ${tableHtml(
        [
          { label: "State", cell: (s) => `<strong>${esc(s.state)}</strong>` },
          { label: `${L.brand} retailers`, cell: (s) => bar(s.brand_retailers, stateMax) },
          { label: "Our stockists", cell: (s) => bar(s.stockists, stateMax, true) },
          { label: "Gap", num: true, cell: (s) => `${s.gap > 0 ? "+" : ""}${num(s.gap)}` },
        ],
        states,
        {},
      )}
    </section>`;
}

// Tabs

const TABS = [
  ["opp", "Stores to approach", D.opportunities.filter((r) => r.watched.length).length, renderOpp],
  ["brands", "Brands", D.brands.length, renderBrands],
  ["regions", "Regions", D.regions.length, renderRegions],
  ["lists", "Published lists", D.survey.filter((s) => s.status === "full").length, renderLists],
];
let tab = "opp";

function renderTabs() {
  $("#tabs").innerHTML = TABS.map(
    ([key, label, count]) => `<button type="button" role="tab" data-tab="${key}" aria-selected="${key === tab}">${esc(label)} <small>${num(count)}</small></button>`,
  ).join("");
  for (const b of document.querySelectorAll("[data-tab]")) {
    b.addEventListener("click", () => {
      tab = b.dataset.tab;
      renderTabs();
    });
  }
  TABS.find(([key]) => key === tab)[3]();
}

paintIcons();
renderTabs();
