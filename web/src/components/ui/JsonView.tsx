import { Check, Copy, Download } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

const TOKEN = /("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

function highlight(json: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of json.matchAll(TOKEN)) {
    const index = m.index ?? 0;
    if (index > last) out.push(json.slice(last, index));
    const token = m[0];
    const kind = token.startsWith('"') ? (m[2] ? "key" : "string") : /true|false|null/.test(token) ? "literal" : "number";
    out.push(
      <span key={index} className={`json-${kind}`}>
        {token}
      </span>,
    );
    last = index + token.length;
  }
  out.push(json.slice(last));
  return out;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** A scrollable, highlighted JSON document with its size, copy and download. */
export function JsonView({ value, filename, note }: { value: unknown; filename: string; note?: string }) {
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);
  const [copied, setCopied] = useState(false);
  const size = new Blob([text]).size;

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="json-view">
      <div className="json-bar">
        <span className="mono muted">{formatBytes(size)}</span>
        {note && <span className="mono muted small">{note}</span>}
        <span className="spacer" />
        <button type="button" className="icon-button" aria-label="Unduh JSON ini" onClick={download}>
          <Download size={15} />
        </button>
        <button type="button" className="icon-button" aria-label={copied ? "Tersalin" : "Salin JSON"} onClick={copy}>
          {copied ? <Check size={15} /> : <Copy size={15} />}
        </button>
      </div>
      <pre className="json-body" data-testid="json-view">
        <code>{highlight(text)}</code>
      </pre>
    </div>
  );
}
