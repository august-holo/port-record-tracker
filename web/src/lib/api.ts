import type { Exhibit, ExhibitQuery, OptionsResponse, SourcesResponse, Terminal } from "./types";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const fetchSources = () => get<SourcesResponse>("/api/sources");
export const fetchOptions = (terminal: Terminal) => get<OptionsResponse>(`/api/options?terminal=${terminal}`);

export function fetchExhibit(q: ExhibitQuery) {
  const p = new URLSearchParams({
    terminal: q.terminal,
    start: q.start,
    end: q.end,
    line: q.line.trim(),
    equipment: q.equipment.trim(),
  });
  return get<Exhibit>(`/api/exhibit?${p}`);
}
