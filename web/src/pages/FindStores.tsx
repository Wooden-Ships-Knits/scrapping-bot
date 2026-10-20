import { AlertTriangle, Search } from "lucide-react";

import type { DiscoverEstimate, DiscoverOptions, Discovery } from "../api/client";
import {
  costLine,
  countryLabel,
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
  // Stores a run read recently: a search leaves them out and counts only new ones, a run
  // on pasted links loads their data. True scrapes them again in both cases.
  rescrape: boolean;
  prompt: string; // the search in the operator's own words; it only fills in this form
  place: string; // one named place ("Las Vegas, NV") instead of a region; "" uses `region`
  country: string; // the place's country code
  // States and provinces ticked in a North American region ("US-TN"); the agent asks about
  // each in turn. Other regions have none.
  states: string[];
};

/** What reading a described search gave: the settings it filled in, or why it was refused. */
export type PromptNote = { ok: boolean; text: string };

export const OTHER = "other";

export function parseCount(text: string, max: number): number | null {
  const n = Number(text.trim());
  return Number.isInteger(n) && n >= 1 && n <= max ? n : null;
}

/** The states and provinces a region can be narrowed to; none outside North America. */
export function regionStates(options: DiscoverOptions, region: string): string[] {
  return options.region_states[region] ?? [];
}

/** What a search sends: the ticked states, unless a single place was named. */
export function sentStates(options: DiscoverOptions, form: FindForm): string[] {
  return form.place ? [] : form.states.filter((s) => regionStates(options, form.region).includes(s));
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
  onInterpret,
  interpreting = false,
  promptNote,
}: {
  options: DiscoverOptions;
  form: FindForm;
  estimate?: DiscoverEstimate | null; // what this search can cost; absent while it is unknown
  onChange: (form: FindForm) => void;
  onInterpret?: () => void; // read `form.prompt` and fill in the fields
  interpreting?: boolean;
  promptNote?: PromptNote | null;
}) {
  const countOk = parseCount(form.count, options.max_count) !== null;
  const toggleItem = (item: string) =>
    onChange({
      ...form,
      items: form.items.includes(item) ? form.items.filter((i) => i !== item) : [...form.items, item],
    });
  const codes = form.place ? [] : regionStates(options, form.region);
  const stateBy = new Map(options.states.map((st) => [st.code, st]));
  const countries = [...new Set(codes.map((c) => stateBy.get(c)?.country ?? ""))];
  const setStates = (states: string[]) => onChange({ ...form, states: codes.filter((c) => states.includes(c)) });
  const toggleState = (code: string) =>
    setStates(form.states.includes(code) ? form.states.filter((c) => c !== code) : [...form.states, code]);
  const active = Object.entries(options.sources).filter(([, on]) => on);
  // "gemini/… then openai/…": the second takes over when the first fails.
  const agentModels = [options.agent_model, ...options.agent_fallbacks].join(", then ");
  const missing = Object.entries(options.sources).filter(([, on]) => !on);

  return (
    <div className="find-fields">
      {options.prompt_model && onInterpret && (
        <div className="find-field find-prompt">
          <label htmlFor="find-prompt">Describe the search (optional)</label>
          <div className="find-prompt-row">
            <input
              id="find-prompt"
              value={form.prompt}
              maxLength={options.max_prompt_chars}
              onChange={(e) => onChange({ ...form, prompt: e.target.value })}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                e.preventDefault(); // Enter fills in the form; it never starts the paid search
                if (form.prompt.trim() && !interpreting) onInterpret();
              }}
              placeholder="e.g. cashmere and knitwear boutiques in Las Vegas"
            />
            <button type="button" className="chip" disabled={!form.prompt.trim() || interpreting} onClick={onInterpret}>
              {interpreting ? "Reading…" : "Fill in the form"}
            </button>
          </div>
          <small className="muted">
            Read once by {options.prompt_model}, for a fraction of a cent. It only fills in the fields below: nothing is
            searched until you start. Store, brand, product or wholesale research only.
          </small>
          {promptNote && (
            <div
              className={`notice ${promptNote.ok ? "info" : "bad"}`}
              role={promptNote.ok ? "status" : "alert"}
              data-testid="prompt-note"
            >
              {promptNote.text}
            </div>
          )}
        </div>
      )}

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

      {form.place ? (
        <div className="find-field" data-testid="find-place">
          <span>Place</span>
          <div className="find-place">
            <strong>{form.place}</strong> <span className="muted">({form.country})</span>
          </div>
          <button type="button" className="link-button" onClick={() => onChange({ ...form, place: "", country: "" })}>
            Use a region instead
          </button>
        </div>
      ) : (
        <label className="find-field">
          <span>Region</span>
          <select
            value={form.region}
            onChange={(e) =>
              onChange({ ...form, region: e.target.value, states: regionStates(options, e.target.value) })
            }
          >
            {options.regions.map((r) => (
              <option key={r} value={r}>
                {regionLabel(r)}
              </option>
            ))}
          </select>
        </label>
      )}

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

      {codes.length > 0 && (
        <fieldset className="find-field find-states" data-testid="find-states">
          <legend>
            States and provinces ({formatNumber(sentStates(options, form).length)} of {formatNumber(codes.length)})
          </legend>
          {countries.map((country) => {
            const own = codes.filter((c) => stateBy.get(c)?.country === country);
            return (
              <div key={country} className="find-state-group" role="group" aria-label={countryLabel(country)}>
                <div className="find-state-head">
                  <strong>{countryLabel(country)}</strong>
                  <button type="button" className="link-button" onClick={() => setStates([...form.states, ...own])}>
                    All
                  </button>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => setStates(form.states.filter((c) => !own.includes(c)))}
                  >
                    None
                  </button>
                </div>
                <div className="find-checks find-state-checks">
                  {own.map((code) => (
                    <label key={code} className="menu-check">
                      <input type="checkbox" checked={form.states.includes(code)} onChange={() => toggleState(code)} />
                      {stateBy.get(code)?.name ?? code}
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
          <small className="muted">
            The AI agent asks about each ticked state in turn, those earlier searches found the fewest stores in first.
          </small>
        </fieldset>
      )}

      <p className="muted small find-sources" data-testid="find-sources">
        Active sources:{" "}
        {active.length
          ? active
              .map(([s]) => (s === "ai_agent" ? `${discoverySourceLabel(s)} (${agentModels})` : discoverySourceLabel(s)))
              .join(", ")
          : "none"}
        {missing.length > 0 && <> · no API key: {missing.map(([s]) => discoverySourceLabel(s)).join(", ")}</>}
      </p>

      {options.reuse_days > 0 && (
        <label className="menu-check find-rescrape">
          <input
            type="checkbox"
            checked={form.rescrape}
            onChange={(e) => onChange({ ...form, rescrape: e.target.checked })}
          />
          <span>
            Include stores already scraped in the last {formatNumber(options.reuse_days)} days, and scrape them again
            <span className="muted small">
              {" "}
              (otherwise the search is for new stores only: those are skipped and not counted)
            </span>
          </span>
        </label>
      )}

      {estimate && estimate.lines.length > 0 && (
        <div className="notice info find-estimate" role="status" data-testid="find-estimate">
          <strong>
            Estimated cost for {plural(estimate.count, "store")}: up to {formatUsd(estimate.max_usd)}
          </strong>{" "}
          {estimate.lines
            .map((l) => `${costLine(l.name)} up to ${formatUsd(l.max_usd)}${l.note ? ` (${l.note})` : ""}`)
            .join(" · ")}
          <small className="muted">
            {" "}
            List prices and caps, not a bill: free allowances are not subtracted, and search answers already cached
            cost nothing. A search for new stores asks the AI agent afresh each time.
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
          <strong>{plural(discovery.found, "new store")} found</strong>
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
          <p className="muted">{plural(discovery.stores_to_visit, "new store")} handed to the run…</p>
        )}
        {discovery.read_before > 0 && (
          <p className="muted small" data-testid="discovery-read-before">
            {plural(discovery.read_before, "store")} found had been scraped before: left out, not counted.
          </p>
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
