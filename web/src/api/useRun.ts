import { useEffect, useState } from "react";

import { api, ApiError, FINISHED, type Run } from "./client";

const POLL_MS = 2000;

/** The live state of a run: server-sent events while it runs, polling as a fallback. */
export function useRun(runId: string): { run: Run | null; error: string } {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stopped = false;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setRun(null);
    setError("");

    const accept = (next: Run) => {
      if (stopped) return;
      setRun(next);
      if (FINISHED.includes(next.state)) stop();
    };
    const stop = () => {
      stopped = true;
      source?.close();
      clearTimeout(timer);
    };
    const poll = async () => {
      try {
        accept(await api.run(runId));
      } catch (e) {
        if (stopped) return;
        setError(e instanceof ApiError ? e.message : "Server tidak bisa dihubungi.");
        if (e instanceof ApiError && e.status === 404) return stop();
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS);
    };

    if (typeof EventSource === "undefined") {
      void poll();
    } else {
      source = new EventSource(api.eventsUrl(runId));
      source.addEventListener("run", (event) => {
        setError("");
        accept(JSON.parse((event as MessageEvent<string>).data) as Run);
      });
      source.onerror = () => {
        // The stream ends when the run ends, or drops; either way fall back to polling.
        source?.close();
        if (!stopped) void poll();
      };
    }
    return stop;
  }, [runId]);

  return { run, error };
}
