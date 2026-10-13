import { AlertTriangle, Search } from "lucide-react";

import type { DiscoverEstimate, DiscoverOptions, Discovery } from "../api/client";
import {
  costLine,
  discoverySourceLabel,
  discoveryState,
  formatNumber,
  formatUsd,
  itemLabel,
  plural,
  regionLabel,
  sourceStatus,
} from "../labels";

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
  estimate,
  onChange,
}: {
  options: DiscoverOptions;
  form: FindForm;
  estimate?: DiscoverEstimate | null; // what this search can cost; absent while it is unknown
  onChange: (form: FindForm) => void;
}) {
  const countOk = parseCount(form.count, options.max_count) !== null;
  const toggleItem = (item: string) =>
    onChange({
      ...form,
      items: form.items.includes(item) ? form.items.filter((i) => i !== item) : [...form.items, item],
    });
  const active = Object.entries(options.sources).filter(([, on]) => on);
  // "gemini/… then openai/…": the second takes over when the first fails.
  const agentModels = [options.agent_model, ...options.agent_fallbacks].join(", then ");
  const missing = Object.entries(options.sources).filter(([, on]) => !on);

  return (
    <div className="find-fields">
      <label className="find-field">
        <span>Number of stores</span>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          max={options.max_count}
          value={form.count}
          aria-invalid={!countOk}
          onChange={(e) => onChange({ ...form, count: e.target.value })}
          placeholder="e.g. 50"
        />
        <small className={countOk ? "muted" : "bad-text"}>1 – {formatNumber(options.max_count)} stores</small>
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
        <legend>Items to look for</legend>
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
            aria-label="Keywords for other items"
            value={form.terms}
            onChange={(e) => onChange({ ...form, terms: e.target.value })}
            placeholder="separate with commas, e.g. poncho, cape"
          />
        )}
      </fieldset>

      <p className="muted small find-sources" data-testid="find-sources">
        Active sources:{" "}
        {active.length
          ? active
              .map(([s]) => (s === "ai_agent" ? `${discoverySourceLabel(s)} (${agentModels})` : discoverySourceLabel(s)))
              .join(", ")
          : "none"}
        {missing.length > 0 && <> · no API key: {missing.map(([s]) => discoverySourceLabel(s)).join(", ")}</>}
      </p>

      {estimate && estimate.lines.length > 0 && (
        <div className="notice info find-estimate" role="status" data-testid="find-estimate">
          <strong>Estimated cost: up to {formatUsd(estimate.max_usd)}</strong> for {plural(estimate.count, "store")}.{" "}
          {estimate.lines
            .map((l) => `${costLine(l.name)} up to ${formatUsd(l.max_usd)}${l.note ? ` (${l.note})` : ""}`)
            .join(" · ")}
          <small className="muted">
            {" "}
            List prices and caps, not a bill: answers already cached cost nothing, and free allowances are not
            subtracted.
          </small>
        </div>
      )}
    </div>
  );
}

/** Live state of a discovery until its run starts. */
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
          <strong>{plural(discovery.found, "store")} found</strong>
          <span className="muted"> / target {formatNumber(discovery.count)}</span>
        </span>
      </div>
      <div className="find-progress">
        {discovery.state === "searching" && (
          <p className="muted">
            {discovery.step ? `Searching with ${discoverySourceLabel(discovery.step)}… ` : "Starting the search… "}
            This can take a few minutes; scraping every store found starts automatically afterwards.
          </p>
        )}
        {discovery.state === "starting_run" && (
          <p className="muted">{plural(discovery.stores_to_visit, "store")} handed to the run…</p>
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
                <th>Source</th>
                <th>Status</th>
                <th className="end">Found</th>
                <th className="end">Est. cost</th>
              </tr>
            </thead>
            <tbody>
              {discovery.sources.map((s) => (
                <tr key={s.name}>
                  <td>{discoverySourceLabel(s.name)}</td>
                  <td title={s.error}>{sourceStatus(s.status)}</td>
                  <td className="end">{formatNumber(s.found)}</td>
                  <td className="end">{s.cost_usd > 0 ? formatUsd(s.cost_usd) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {discovery.sources.some((s) => s.notes.length > 0) && (
          <ul className="muted small" data-testid="discovery-notes">
            {discovery.sources.flatMap((s) =>
              s.notes.map((note) => (
                <li key={`${s.name}-${note}`}>
                  {discoverySourceLabel(s.name)}: {note}
                </li>
              )),
            )}
          </ul>
        )}
        {discovery.cost_usd > 0 && (
          <p className="muted small" data-testid="discovery-cost">
            Estimated API cost of this search: <strong>{formatUsd(discovery.cost_usd)}</strong> (list prices; the website
            lookup is included).
          </p>
        )}
      </div>
    </section>
  );
}
