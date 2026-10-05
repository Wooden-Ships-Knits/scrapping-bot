import type { Preview } from "../api/client";
import { formatNumber, skipReason } from "../labels";

export function PreviewPanel({ preview, loading }: { preview: Preview | null; loading: boolean }) {
  if (!preview) {
    return (
      <p className="muted" aria-live="polite">
        {loading ? "Membaca tautan…" : "Belum ada tautan."}
      </p>
    );
  }
  const skipped = Object.entries(preview.skipped);
  return (
    <div className="preview" aria-live="polite" data-testid="preview">
      <p className="preview-line">
        Terdeteksi <strong>{formatNumber(preview.links)}</strong> tautan ·{" "}
        <strong>{formatNumber(preview.stores)}</strong> toko unik
        {preview.duplicates > 0 && <> · {formatNumber(preview.duplicates)} duplikat</>}
        {loading && <span className="muted"> (memperbarui…)</span>}
      </p>
      {skipped.length > 0 && (
        <p className="muted">
          Dilewati: {skipped.map(([reason, n]) => `${skipReason(reason)} ${n}`).join(", ")}
        </p>
      )}
      {preview.too_many && (
        <p className="alert alert-bad">
          Terlalu banyak: maksimal {formatNumber(preview.max_links)} tautan per run. Pecah daftarnya.
        </p>
      )}
      {preview.store_examples.length > 0 && (
        <p className="muted small">
          Contoh toko: {preview.store_examples.join(", ")}
          {preview.stores > preview.store_examples.length && ", …"}
        </p>
      )}
    </div>
  );
}
