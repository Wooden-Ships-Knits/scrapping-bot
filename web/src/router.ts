import { useEffect, useState } from "react";

// Hash routes keep the app a static bundle that any server can host:
//   #/            new run
//   #/runs        history
//   #/runs/<id>   one run

export type Route = { page: "new" } | { page: "history" } | { page: "run"; runId: string };

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, "") || "/";
  const run = path.match(/^\/runs\/([\w-]+)$/);
  if (run?.[1]) return { page: "run", runId: run[1] };
  if (path === "/runs") return { page: "history" };
  return { page: "new" };
}

export function navigate(path: string) {
  window.location.hash = path;
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
