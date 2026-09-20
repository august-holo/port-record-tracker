/** Mirrors src/api.py. Keep in sync by hand; the API is small. */

export type Terminal = "T18" | "T5" | "Husky" | "PCT" | "WUT";

export interface SourceInfo {
  source_id: string;
  url: string;
  publisher: string;
  terminal: string | null;
  channel: "gate" | "empties" | "bulletin" | "turn_time" | "erd" | "slots";
  cadence_minutes: number;
  mock: boolean;
  status: string;
  captures: number;
  versions: number;
  errors: number;
  parsed_rows: number;
  first: string | null;
  last: string | null;
}

export interface OptionsResponse {
  terminal: Terminal;
  lines: string[];
  equipment: string[];
}

export interface SourcesResponse {
  sources: SourceInfo[];
  terminals: Terminal[];
}

export interface Evidence {
  capture_id: number;
  source_id: string;
  fetched_at_utc: string;
  fetched_at_pt: string;
  hash: string;
  mock: boolean;
}

export interface GateFact {
  status: "open" | "closed";
  shift: string | null;
  cell_raw: string | null;
  asserted_by_captures: Record<string, number[]>;
  changed_between_captures: boolean;
  first_seen_utc: string;
  last_seen_utc: string;
}

export interface EmptyRule {
  line: string;
  equipment: string;
  action: "drop" | "pick" | "any";
  accepted: boolean;
  cell_raw: string | null;
  as_of_iso: string | null;
  heading: string | null;
}

export interface EmptiesFact {
  from_capture: number;
  capture_pt_date: string;
  same_day: boolean;
  rules: EmptyRule[];
}

export interface Notice {
  text: string | null;
  url: string | null;
  posted_iso: string | null;
  keywords: string[] | null;
  scope: string;
  evidence: number;
}

export interface TurnTimesFact {
  samples: number;
  na_samples: number;
  placeholder_only: boolean;
  queue_min_max: number | null;
  queue_min_min: number | null;
  evidence: number[];
}

export interface SlotQuery {
  query: { trade_type: string | null; pick_drop: string | null; equipment: string | null; line: string | null };
  samples: number;
  samples_with_slot_that_day: number;
  evidence: number[];
}

export interface SlotsFact {
  mock: boolean;
  queries: SlotQuery[];
}

export interface Answers {
  gate_scheduled_open: boolean | null;
  empties_accepted: boolean | null;
  unscheduled_closure_or_restriction_noticed: boolean | null;
  appointments_available: boolean | null;
  appointments_source_is_mock: boolean;
  government_hold: null;
}

export interface Day {
  date: string;
  weekday: string;
  gate: GateFact | null;
  empties: EmptiesFact | null;
  notices: Notice[];
  turn_times: TurnTimesFact | null;
  slots: SlotsFact | null;
  answers: Answers;
}

export interface ChannelStatus {
  source_id: string;
  channel: SourceInfo["channel"];
  mock: boolean;
  parsed_rows_in_range: number;
}

export interface Exhibit {
  terminal: Terminal;
  start: string;
  end: string;
  filters: { line: string | null; equipment: string | null };
  generated_at_utc: string;
  timezone: string;
  caveat: string;
  days: Day[];
  channels: ChannelStatus[];
  captures: Evidence[];
}

/** A day to check, optionally narrowed to a time window. Blank times = all day. */
export interface CheckDate {
  date: string;
  from: string;
  to: string;
}

export interface ExhibitQuery {
  terminal: Terminal;
  start: string;
  end: string;
  line: string;
  equipment: string;
}
