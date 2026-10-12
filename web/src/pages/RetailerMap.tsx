import { Search } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { ApiError, api, type RetailerMap as MapData } from "../api/client";
import { brandKind, formatNumber, locatorStatus, matchGroup, territoryLabel } from "../labels";

type Opportunity = MapData["opportunities"][number];
type Brand = MapData["brands"][number];
type Region = MapData["regions"][number];
type Survey = MapData["survey"][number];
type PublishedList = NonNullable<MapData["locator"]>;
type Tab = "stores" | "brands" | "regions" | "lists";

const PAGE = 15;
const GROUPS = ["same", "check", "near", "open"];
const TERRITORY_TONE: Record<string, string> = { open: "good", near: "warn", unknown: "neutral" };
const LOCATOR_TONE: Record<string, string> = { full: "good", area: "warn", robots: "bad", own: "neutral", none: "neutral" };

const count = (n: number | null | undefined) => (n === null || n === undefined ? "—" : formatNumber(n));
const percent = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : n > 0 && n < 0.01 ? "<1%" : `${Math.round(n * 100)}%`;
const dash = <span className="muted">—</span>;

/** Where brands like ours are sold, from the newest run the process has read. */
export function RetailerMap() {
  const [data, setData] = useState<MapData | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<Tab>("stores");
  const [filter, setFilter] = useState<StoreFilter>({ brand: "watched", territory: "all", email: false, query: "" });

  useEffect(() => {
    api
      .retailerMap()
      .then(setData)
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e : new ApiError(0, "unreachable", "The server cannot be reached.")),
      );
  }, []);

  const tabs: [Tab, string, number][] = data
    ? [
        ["stores", "Stores to approach", data.watched_not_ours],
        ["brands", "Brands", data.brands.length],
        ["regions", "Regions", data.regions.length],
        ["lists", "Published lists", data.survey.filter((s) => s.status === "full").length],
      ]
    : [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Retailer map</h1>
          <p>
            Where brands like ours are sold, read from the catalogues of the stores in one run
            {data ? `: ${formatNumber(data.readable)} of ${formatNumber(data.stores)} stores were readable.` : "."}
          </p>
        </div>
        {data && (
          <div className="page-actions">
            <a className="chip mono small" href={`#/runs/${data.run_id}`} title="Open this run">
              <span className="muted">Run</span> {data.run_id}
            </a>
          </div>
        )}
      </header>

      {error && <div className={`notice ${error.code === "no_process_output" ? "warn" : "bad"}`}>{error.message}</div>}

      {data && (
        <>
          <div className="notice info">
            <strong>Counts are a sample.</strong>
            <span>
              They cover the stores the bot could read, not every retailer of a brand. Scores and thresholds come from
              the exploratory process and are not final.
            </span>
          </div>

          <dl className="stats">
            <Tile
              label="Stores read"
              value={data.readable}
              sub={`of ${formatNumber(data.stores)} in the run · ${formatNumber(data.stores - data.readable)} not read`}
            />
            <Tile
              label="Carry a watched brand"
              value={data.watched_stores}
              sub={data.watched.map((w) => `${w.brand} ${formatNumber(w.stores)}`).join(" · ")}
            />
            <Tile
              label="Of those, not yet ours"
              value={data.watched_not_ours}
              sub={`${formatNumber(data.watched_email)} with an email address · ${formatNumber(data.watched_customers)} already stockists`}
            />
            <Tile
              label="In open territory"
              value={data.watched_territory.open ?? 0}
              sub={`No stockist within ${formatNumber(data.radius_miles)} miles · ${formatNumber(data.watched_territory.near ?? 0)} near one · ${formatNumber(data.watched_territory.unknown ?? 0)} location unknown`}
            />
          </dl>

          <section className="card rm-tabs">
            <div className="tabs-row">
              <div className="tabs" role="tablist" aria-label="Views">
                {tabs.map(([key, label, n]) => (
                  <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>
                    {label} <small>{formatNumber(n)}</small>
                  </button>
                ))}
              </div>
            </div>
          </section>

          <div className="rm-panel">
            {tab === "stores" && <Stores data={data} filter={filter} onFilter={setFilter} />}
            {tab === "brands" && <Brands brands={data.brands} />}
            {tab === "regions" && <Regions data={data} />}
            {tab === "lists" && <Lists survey={data.survey} list={data.locator} />}
          </div>

          <section className="card">
            <div className="card-head">
              <h2>What this page does not show</h2>
              <p>
                {formatNumber(data.stores - data.readable)} of the {formatNumber(data.stores)} stores in this run could
                not be read. They are unknown, not irrelevant. A brand's count is the number of read stores that sell
                it, so it cannot be read as a share of that brand's retailers. "Ours" is measured against the stockist
                list only, until an account export is added. {formatNumber(data.opportunities.length - data.located)}{" "}
                of {formatNumber(data.opportunities.length)} stores have no known location.
              </p>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: number; sub: string }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>{formatNumber(value)}</dd>
      <p className="sub">{sub}</p>
    </div>
  );
}

// A table whose columns may sort. `sort` returns the value a column sorts by; empty values go last.

type Column<T> = {
  label: string;
  cell: (row: T) => ReactNode;
  num?: boolean;
  wrap?: boolean;
  sort?: (row: T) => number | string | null | undefined;
};
type Sort = { column: number; down: boolean } | null;

function sortRows<T>(rows: T[], columns: Column<T>[], sort: Sort): T[] {
  const value = sort ? columns[sort.column]?.sort : undefined;
  if (!sort || !value) return rows;
  const direction = sort.down ? -1 : 1;
  return [...rows].sort((a, b) => {
    const x = value(a) ?? null;
    const y = value(b) ?? null;
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    return (typeof x === "string" ? x.localeCompare(String(y)) : x - Number(y)) * direction;
  });
}

/** First click sorts largest first, the second reverses. */
const nextSort = (sort: Sort, column: number): Sort => ({ column, down: sort?.column === column ? !sort.down : true });

function SortTable<T>({
  columns,
  rows,
  rowKey,
  sort = null,
  onSort,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  sort?: Sort;
  onSort?: (column: number) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c, i) => {
              const active = sort?.column === i;
              return (
                <th
                  key={c.label}
                  className={c.num ? "num" : undefined}
                  aria-sort={active ? (sort.down ? "descending" : "ascending") : undefined}
                >
                  {c.sort && onSort ? (
                    <button type="button" onClick={() => onSort(i)}>
                      {c.label}
                      {active ? (sort.down ? " ↓" : " ↑") : ""}
                    </button>
                  ) : (
                    c.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c) => (
                <td key={c.label} className={[c.num ? "num" : "", c.wrap ? "rm-wrap" : ""].join(" ").trim() || undefined}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pager({ page, total, noun, onPage }: { page: number; total: number; noun: string; onPage: (page: number) => void }) {
  const last = Math.max(0, Math.ceil(total / PAGE) - 1);
  return (
    <div className="pager">
      <span>
        {total ? `${page * PAGE + 1}–${Math.min(total, (page + 1) * PAGE)} of ${formatNumber(total)} ${noun}` : `0 ${noun}`}
      </span>
      <button type="button" className="button ghost small-button" disabled={page === 0} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <button type="button" className="button ghost small-button" disabled={page >= last} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}

function Segmented<K extends string>({
  name,
  options,
  value,
  onChange,
}: {
  name: string;
  options: [K, string, number?][];
  value: K;
  onChange: (value: K) => void;
}) {
  return (
    <div className="segmented" role="tablist" aria-label={name}>
      {options.map(([key, label, n]) => (
        <button key={key} type="button" role="tab" aria-selected={value === key} onClick={() => onChange(key)}>
          {label}
          {n === undefined ? "" : ` · ${formatNumber(n)}`}
        </button>
      ))}
    </div>
  );
}

function Bar({ value, max, quiet = false }: { value: number; max: number; quiet?: boolean }) {
  return (
    <span className="rm-bar">
      <span className="share-track" aria-hidden="true">
        <span className={`share-fill ${quiet ? "rm-quiet" : ""}`} style={{ width: `${max ? (100 * value) / max : 0}%` }} />
      </span>
      <span className="num">{formatNumber(value)}</span>
    </span>
  );
}

// Stores to approach

type StoreFilter = { brand: string; territory: string; email: boolean; query: string };

function Stores({
  data,
  filter,
  onFilter,
}: {
  data: MapData;
  filter: StoreFilter;
  onFilter: (filter: StoreFilter) => void;
}) {
  const [sort, setSort] = useState<Sort>(null);
  const [page, setPage] = useState(0);
  const all = data.opportunities;
  const name = Object.fromEntries(data.watched.map((w) => [w.key, w.brand]));
  const change = (patch: Partial<StoreFilter>) => {
    onFilter({ ...filter, ...patch });
    setPage(0);
  };

  const columns: Column<Opportunity>[] = [
    {
      label: "Store",
      cell: (r) => (
        <>
          <a href={`https://${r.domain}`} target="_blank" rel="noreferrer">
            {r.name || r.domain}
          </a>
          <span className="sub">{[r.city, r.state].filter(Boolean).join(", ") || "location unknown"}</span>
        </>
      ),
    },
    {
      label: "Watched brands",
      wrap: true,
      sort: (r) => r.watched.length,
      cell: (r) =>
        r.watched.length ? (
          <span className="rm-tags">
            {r.watched.map((key) => (
              <span key={key} className="tag solid">
                {name[key] ?? key}
              </span>
            ))}
          </span>
        ) : (
          dash
        ),
    },
    {
      label: "Other relevant brands",
      sort: (r) => r.relevant.length,
      cell: (r) =>
        r.relevant.length ? (
          <span title={r.relevant.join(", ")}>
            {r.relevant.slice(0, 2).join(", ")}
            {r.relevant.length > 2 && <span className="muted"> +{r.relevant.length - 2}</span>}
          </span>
        ) : (
          dash
        ),
    },
    { label: "Knit products", num: true, sort: (r) => r.knit, cell: (r) => formatNumber(r.knit) },
    {
      label: "Knit median",
      num: true,
      cell: (r) => (r.price === null ? "—" : `${formatNumber(Math.round(r.price))} ${r.currency ?? ""}`),
    },
    {
      label: "Territory",
      sort: (r) => r.miles,
      cell: (r) => (
        <>
          <span className={`badge badge-${TERRITORY_TONE[r.territory] ?? "neutral"}`}>{territoryLabel(r.territory)}</span>
          {r.miles !== null && <span className="sub">nearest stockist {r.miles.toFixed(1)} mi</span>}
        </>
      ),
    },
    { label: "Email", cell: (r) => (r.email ? "Yes" : dash) },
    { label: "Store score", num: true, sort: (r) => r.score, cell: (r) => count(r.score) },
  ];

  const query = filter.query.trim().toLowerCase();
  const rows = sortRows(
    all.filter(
      (r) =>
        (filter.brand === "all" ||
          (filter.brand === "watched" ? r.watched.length > 0 : r.watched.includes(filter.brand))) &&
        (filter.territory === "all" || r.territory === filter.territory) &&
        (!filter.email || r.email) &&
        (!query ||
          [r.domain, r.name, r.city, r.state, ...r.relevant, ...r.watched.map((key) => name[key])].some((v) =>
            v?.toLowerCase().includes(query),
          )),
    ),
    columns,
    sort,
  );
  const shown = Math.min(page, Math.max(0, Math.ceil(rows.length / PAGE) - 1));

  return (
    <section className="card" aria-label="Stores to approach">
      <div className="card-head">
        <h2>Stores to approach</h2>
        <span className="muted small">retail partner candidates that are not stockists</span>
        <p>
          Each store was read by the bot and sells the brands shown. Listed as the process ranked them; click a column
          to re-sort (Territory sorts by distance to the nearest stockist).
        </p>
      </div>
      <div className="rm-filters">
        <Segmented
          name="Brand"
          value={filter.brand}
          onChange={(brand) => change({ brand })}
          options={[
            ["watched", "Any watched brand", all.filter((r) => r.watched.length).length],
            ...data.watched.map((w): [string, string, number] => [
              w.key,
              w.brand,
              all.filter((r) => r.watched.includes(w.key)).length,
            ]),
            ["all", "All candidates", all.length],
          ]}
        />
        <Segmented
          name="Territory"
          value={filter.territory}
          onChange={(territory) => change({ territory })}
          options={[
            ["all", "Any territory"],
            ["open", "Open"],
            ["near", "Stockist nearby"],
            ["unknown", "Unknown"],
          ]}
        />
        <label className="rm-check">
          <input type="checkbox" checked={filter.email} onChange={(e) => change({ email: e.target.checked })} /> Has an
          email
        </label>
        <label className="search">
          <Search size={15} aria-hidden="true" />
          <input
            type="search"
            placeholder="Store, city or brand"
            aria-label="Search stores"
            value={filter.query}
            onChange={(e) => change({ query: e.target.value })}
          />
        </label>
      </div>
      {rows.length ? (
        <SortTable
          columns={columns}
          rows={rows.slice(shown * PAGE, (shown + 1) * PAGE)}
          rowKey={(r) => r.domain}
          sort={sort}
          onSort={(column) => {
            setSort(nextSort(sort, column));
            setPage(0);
          }}
        />
      ) : (
        <p className="empty">No store matches these filters.</p>
      )}
      <Pager page={shown} total={rows.length} noun="stores" onPage={setPage} />
    </section>
  );
}

// Brands

function Brands({ brands }: { brands: Brand[] }) {
  const [kind, setKind] = useState("all");
  const [sort, setSort] = useState<Sort>(null);
  const [page, setPage] = useState(0);
  const most = Math.max(1, ...brands.map((b) => b.stores));

  const columns: Column<Brand>[] = [
    {
      label: "Brand",
      wrap: true,
      cell: (b) => (
        <span className="rm-brand">
          {b.brand}
          {b.watched && <span className="tag solid">Watched</span>}
        </span>
      ),
    },
    { label: "Type", cell: (b) => <span className="tag">{brandKind(b.kind)}</span> },
    { label: "Stores selling it", sort: (b) => b.stores, cell: (b) => <Bar value={b.stores} max={most} /> },
    { label: "Also ours", num: true, sort: (b) => b.shared, cell: (b) => formatNumber(b.shared) },
    { label: "Not ours", num: true, sort: (b) => b.not_ours, cell: (b) => formatNumber(b.not_ours) },
    { label: "In open territory", num: true, sort: (b) => b.open, cell: (b) => formatNumber(b.open) },
    { label: "Knitwear share", num: true, sort: (b) => b.knit_share, cell: (b) => percent(b.knit_share) },
    {
      label: "Price vs ours",
      num: true,
      sort: (b) => b.price,
      cell: (b) => (b.price === null ? "—" : `${b.price.toFixed(2)}×`),
    },
    { label: "Relevance", num: true, sort: (b) => b.rank, cell: (b) => (b.rank === null ? "—" : b.rank.toFixed(2)) },
    {
      label: "Coverage",
      cell: (b) =>
        b.full ? (
          <span className="badge badge-good">Sample + full list</span>
        ) : (
          <span className="badge badge-neutral">Sample</span>
        ),
    },
  ];

  const rows = sortRows(
    brands.filter((b) => kind === "all" || (kind === "watched" ? b.watched : b.kind === kind)),
    columns,
    sort,
  );

  return (
    <section className="card" aria-label="Brands">
      <div className="card-head">
        <h2>Brands, by closeness to ours</h2>
        <span className="muted small">brands with enough read stores to be ranked</span>
        <p>
          A knitwear rival holds mostly knitwear. A marker brand holds little, but shows the kind of boutique that suits
          us. Price vs ours compares knitwear prices in US dollars: 1.00× is the same.
        </p>
      </div>
      <div className="rm-filters">
        <Segmented
          name="Brand type"
          value={kind}
          onChange={(k) => {
            setKind(k);
            setPage(0);
          }}
          options={[
            ["all", "All brands", brands.length],
            ["watched", "Watched", brands.filter((b) => b.watched).length],
            ["rival", "Knitwear rivals", brands.filter((b) => b.kind === "rival").length],
            ["marker", "Marker brands", brands.filter((b) => b.kind === "marker").length],
          ]}
        />
      </div>
      <SortTable
        columns={columns}
        rows={rows.slice(page * PAGE, (page + 1) * PAGE)}
        rowKey={(b) => b.key}
        sort={sort}
        onSort={(column) => {
          setSort(nextSort(sort, column));
          setPage(0);
        }}
      />
      <Pager page={page} total={rows.length} noun="brands" onPage={setPage} />
    </section>
  );
}

// Regions

function Regions({ data }: { data: MapData }) {
  const [sort, setSort] = useState<Sort>(null);
  // One scale for both bars, so a long first bar beside a short second one means what it shows.
  const most = Math.max(1, ...data.regions.flatMap((r) => [r.opportunities, r.stockists]));
  const columns: Column<Region>[] = [
    { label: "State or province", sort: (r) => r.state, cell: (r) => <strong>{r.state}</strong> },
    { label: "Stores to approach", sort: (r) => r.opportunities, cell: (r) => <Bar value={r.opportunities} max={most} /> },
    {
      label: "Of those, in open territory",
      num: true,
      sort: (r) => r.open_territory,
      cell: (r) => formatNumber(r.open_territory),
    },
    { label: "Our stockists", sort: (r) => r.stockists, cell: (r) => <Bar value={r.stockists} max={most} quiet /> },
  ];
  return (
    <section className="card" aria-label="Regions">
      <div className="card-head">
        <h2>Where the stores are, against our stockists</h2>
        <span className="muted small">
          {formatNumber(data.located)} of {formatNumber(data.opportunities.length)} candidate stores have a known location
        </span>
        <p>
          Both bars count stores on the same scale. A long first bar beside a short second one is a region where similar
          brands sell and we are thin.
        </p>
      </div>
      <SortTable
        columns={columns}
        rows={sortRows(data.regions, columns, sort)}
        rowKey={(r) => r.state}
        sort={sort}
        onSort={(column) => setSort(nextSort(sort, column))}
      />
    </section>
  );
}

// Published lists

function Lists({ survey, list }: { survey: Survey[]; list: MapData["locator"] }) {
  const columns: Column<Survey>[] = [
    { label: "Brand", cell: (s) => <strong>{s.brand}</strong> },
    { label: "Locator", cell: (s) => s.locator },
    {
      label: "Status",
      cell: (s) => <span className={`badge badge-${LOCATOR_TONE[s.status] ?? "neutral"}`}>{locatorStatus(s.status)}</span>,
    },
    { label: "Locations", num: true, cell: (s) => count(s.locations) },
  ];
  return (
    <>
      <div className="rm-split">
        <section className="card" aria-label="Store locator survey">
          <div className="card-head">
            <h2>Which brands publish their retailers</h2>
            <p>
              A list is read only when the host that serves it allows crawlers and gives the whole list in one request.
            </p>
          </div>
          <SortTable columns={columns} rows={survey} rowKey={(s) => s.brand} />
        </section>
        {list && <ListGroups list={list} />}
      </div>
      {list && <ListStates list={list} />}
    </>
  );
}

function ListGroups({ list }: { list: PublishedList }) {
  const most = Math.max(1, ...GROUPS.map((g) => list.groups[g] ?? 0));
  return (
    <section className="card" aria-label={`${list.brand} published list`}>
      <div className="card-head">
        <h2>
          {list.brand}: {formatNumber(list.total)} published retailers
        </h2>
        <span className="muted small">full list, matched by name and place</span>
      </div>
      <ul className="share-list rm-share">
        {GROUPS.map((g) => {
          const n = list.groups[g] ?? 0;
          return (
            <li key={g}>
              <span>{matchGroup(g)}</span>
              <span className="share-track" aria-hidden="true">
                <span className="share-fill" style={{ width: `${(100 * n) / most}%` }} />
              </span>
              <span className="num">
                {formatNumber(n)} · {percent(list.total ? n / list.total : 0)}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const WIDEST = 12;

function ListStates({ list }: { list: PublishedList }) {
  const most = Math.max(1, ...list.states.flatMap((s) => [s.brand_retailers, s.stockists]));
  const columns: Column<PublishedList["states"][number]>[] = [
    { label: "State", cell: (s) => <strong>{s.state}</strong> },
    { label: `${list.brand} retailers`, cell: (s) => <Bar value={s.brand_retailers} max={most} /> },
    { label: "Our stockists", cell: (s) => <Bar value={s.stockists} max={most} quiet /> },
    { label: "Gap", num: true, cell: (s) => `${s.gap > 0 ? "+" : ""}${formatNumber(s.gap)}` },
  ];
  return (
    <section className="card" aria-label={`${list.brand} retailers by state`}>
      <div className="card-head">
        <h2>{list.brand} retailers against our stockists, by state</h2>
        <span className="muted small">
          {Math.min(WIDEST, list.states.length)} widest gaps of {formatNumber(list.states.length)} states
        </span>
      </div>
      <SortTable columns={columns} rows={list.states.slice(0, WIDEST)} rowKey={(s) => s.state} />
    </section>
  );
}
