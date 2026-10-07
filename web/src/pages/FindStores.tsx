import { AlertTriangle, Search } from "lucide-react";

import type { DiscoverOptions, Discovery } from "../api/client";
import { discoverySourceLabel, discoveryState, formatNumber, itemLabel, regionLabel, sourceStatus } from "../labels";

export type FindForm = {
  count: string; // typed by hand; checked on submit
  region: string;
  items: string[];
  terms: string;
};

export const OTHER = "other";

export function parseCount(text: string, max: number): number | null {
  const n = Number(text.trim());
  return Number.isInteger(n) && n >= 1 && n <= max ? n : null;
}

export function parseTerms(text: string): string[] {
  return text
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/** The settings of a discovery: how many stores, where, and which items. */
export function FindStoresFields({
  options,
  form,
  onChange,
}: {
  options: DiscoverOptions;
  form: FindForm;
  onChange: (form: FindForm) => void;
}) {
  const countOk = parseCount(form.count, options.max_count) !== null;
  const toggleItem = (item: string) =>
    onChange({
      ...form,
      items: form.items.includes(item) ? form.items.filter((i) => i !== item) : [...form.items, item],
    });
  const active = Object.entries(options.sources).filter(([, on]) => on);
  const missing = Object.entries(options.sources).filter(([, on]) => !on);

  return (
    <div className="find-fields">
      <label className="find-field">
        <span>Jumlah toko</span>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          max={options.max_count}
          value={form.count}
          aria-invalid={!countOk}
          onChange={(e) => onChange({ ...form, count: e.target.value })}
          placeholder="contoh: 50"
        />
        <small className={countOk ? "muted" : "bad-text"}>1 – {formatNumber(options.max_count)} toko</small>
      </label>

      <label className="find-field">
        <span>Region</span>
        <select value={form.region} onChange={(e) => onChange({ ...form, region: e.target.value })}>
          {options.regions.map((r) => (
            <option key={r} value={r}>
              {regionLabel(r)}
            </option>
          ))}
        </select>
      </label>

      <fieldset className="find-field find-items">
        <legend>Item yang dicari</legend>
        <div className="find-checks">
          {options.items.map((item) => (
            <label key={item} className="menu-check">
              <input type="checkbox" checked={form.items.includes(item)} onChange={() => toggleItem(item)} />
              {itemLabel(item)}
            </label>
          ))}
        </div>
        {form.items.includes(OTHER) && (
          <input
            aria-label="Kata kunci item lainnya"
            value={form.terms}
            onChange={(e) => onChange({ ...form, terms: e.target.value })}
            placeholder="pisahkan dengan koma, contoh: poncho, cape"
          />
        )}
      </fieldset>

      <p className="muted small find-sources" data-testid="find-sources">
        Sumber aktif:{" "}
        {active.length
          ? active
              .map(([s]) => (s === "ai_agent" ? `${discoverySourceLabel(s)} (${options.agent_model})` : discoverySourceLabel(s)))
              .join(", ")
          : "tidak ada"}
        {missing.length > 0 && <> · tanpa API key: {missing.map(([s]) => discoverySourceLabel(s)).join(", ")}</>}
      </p>
    </div>
  );
}

/** Live state of a discovery until its test run starts. */
export function DiscoveryCard({ discovery }: { discovery: Discovery }) {
  const failed = discovery.state === "failed";
  return (
    <section className="card" data-testid="discovery" aria-live="polite">
      <div className="card-head">
        <h2>
          {failed ? <AlertTriangle size={16} /> : <Search size={16} />} {discoveryState(discovery.state)}
        </h2>
        <span className="spacer" />
        <span className="small">
          <strong>{formatNumber(discovery.found)} toko ditemukan</strong>
          <span className="muted"> / target {formatNumber(discovery.count)}</span>
        </span>
      </div>
      <div className="find-progress">
        {discovery.state === "searching" && (
          <p className="muted">
            {discovery.step ? `Sedang mencari lewat ${discoverySourceLabel(discovery.step)}… ` : "Memulai pencarian… "}
            Ini bisa memakan beberapa menit; run uji dimulai otomatis setelahnya.
          </p>
        )}
        {discovery.state === "starting_run" && (
          <p className="muted">{formatNumber(discovery.stores_to_visit)} toko diserahkan ke run uji…</p>
        )}
        {failed && (
          <div className="notice bad" role="alert">
            {discovery.error}
          </div>
        )}
        {discovery.sources.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Sumber</th>
                <th>Status</th>
                <th className="end">Temuan</th>
              </tr>
            </thead>
            <tbody>
              {discovery.sources.map((s) => (
                <tr key={s.name}>
                  <td>{discoverySourceLabel(s.name)}</td>
                  <td title={s.error}>{sourceStatus(s.status)}</td>
                  <td className="end">{formatNumber(s.found)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {discovery.cost_usd > 0 && <p className="muted small">Biaya agen AI: US${discovery.cost_usd.toFixed(3)}</p>}
      </div>
    </section>
  );
}
