"use client";

import type { CheckDate, Day, Evidence, Exhibit } from "@/lib/types";
import { fmt } from "@/lib/util";
import Info from "./Info";
import { INFO } from "./infoText";
import styles from "./Exhibit.module.css";

function Pill({ answer, text, mock }: { answer: boolean | null; text?: string; mock?: boolean }) {
  const cls = answer === true ? styles.yes : answer === false ? styles.no : styles.unk;
  const label = text ?? (answer === true ? "yes" : answer === false ? "no" : "unknown");
  return (
    <>
      <span className={`${styles.pill} ${cls}`}>{label}</span>
      {answer === null && <Info info={INFO.unknown} />}
      {mock && <span className={`${styles.pill} ${styles.mock}`}>MOCK</span>}
    </>
  );
}

function EvidenceLine({ c }: { c: Evidence }) {
  return (
    <div>
      #{c.capture_id} · {fmt(c.fetched_at_pt)} PT ·{" "}
      <a href={`/raw/${c.hash}`} target="_blank" rel="noreferrer" title="view as captured">
        {c.hash.slice(0, 12)}
      </a>{" "}
      <a href={`/raw/${c.hash}?download=1`} title="download the original file">↓</a>
      {c.mock ? " · MOCK" : ""}
    </div>
  );
}

/** The captures an answer was read from. Many captures usually agree; show the first and last, fold the rest. */
function EvidenceList({ ids, caps }: { ids: number[]; caps: Record<number, Evidence> }) {
  const rows = Array.from(new Set(ids)).map((id) => caps[id]).filter(Boolean);
  if (!rows.length) return null;
  if (rows.length <= 3)
    return (
      <div className={styles.ev}>
        {rows.map((c) => <EvidenceLine key={c.capture_id} c={c} />)}
      </div>
    );
  const middle = rows.slice(1, -1);
  return (
    <div className={styles.ev}>
      <EvidenceLine c={rows[0]} />
      <details>
        <summary>{middle.length} more captures in between say the same</summary>
        {middle.map((c) => <EvidenceLine key={c.capture_id} c={c} />)}
      </details>
      <EvidenceLine c={rows[rows.length - 1]} />
    </div>
  );
}

function GateCell({ d, caps }: { d: Day; caps: Record<number, Evidence> }) {
  const g = d.gate;
  if (!g) return <Pill answer={null} />;
  return (
    <>
      <Pill answer={d.answers.gate_scheduled_open} text={g.status === "open" ? `open ${g.shift ?? ""}`.trim() : "closed"} />
      <div className={styles.detail}>
        published as “{g.cell_raw}”{g.changed_between_captures && <> · <b>changed between captures</b></>}
      </div>
      <EvidenceList ids={Object.values(g.asserted_by_captures).flat()} caps={caps} />
    </>
  );
}

function EmptiesCell({ d, caps }: { d: Day; caps: Record<number, Evidence> }) {
  const e = d.empties;
  if (!e) return <Pill answer={null} />;
  if (!e.rules.length)
    return (
      <>
        <Pill answer={null} text="no rule for this box" />
        <EvidenceList ids={[e.from_capture]} caps={caps} />
      </>
    );
  // Returning an empty is a drop; pick-up rules are listed below but do not decide the answer.
  const returns = e.rules.filter((r) => r.action !== "pick");
  const refused = returns.filter((r) => !r.accepted).length;
  const text = !returns.length ? "no return rule" : refused ? `${refused} of ${returns.length} returns refused` : "accepted";
  return (
    <>
      <Pill answer={d.answers.empties_accepted} text={text} />
      <div className={styles.detail}>
        {e.rules.map((r, i) => (
          <span key={i}>
            {i > 0 && " · "}
            {r.line} {r.equipment} {r.action}: <b>{r.accepted ? "yes" : "NO"}</b>
          </span>
        ))}
        {!e.same_day && <> · <b>from {e.capture_pt_date}</b>, the latest capture before this day</>}
      </div>
      <EvidenceList ids={[e.from_capture]} caps={caps} />
    </>
  );
}

function NoticesCell({ d, caps }: { d: Day; caps: Record<number, Evidence> }) {
  const n = d.notices;
  if (!n.length) return <Pill answer={null} text="none captured" />;
  return (
    <>
      <Pill answer={d.answers.unscheduled_closure_or_restriction_noticed} text={`${n.length} notice${n.length > 1 ? "s" : ""}`} />
      {n.map((m, i) => (
        <p key={i} className={styles.notice}>
          {(m.text ?? "").slice(0, 220)}
          {m.url && (
            <>
              {" "}
              <a href={m.url} target="_blank" rel="noreferrer">↗</a>
            </>
          )}
        </p>
      ))}
      <EvidenceList ids={n.map((m) => m.evidence)} caps={caps} />
    </>
  );
}

const inWindow = (at: string, a: CheckDate) => (!a.from || at >= a.from) && (!a.to || at <= a.to);
const mins = (m: number) => (m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m} min`);

function AtGateCell({ d, a, caps }: { d: Day; a: CheckDate; caps: Record<number, Evidence> }) {
  const readings = (d.turn_times?.readings ?? []).filter((r) => inWindow(r.at_pt, a));
  const frames = (d.cameras?.frames ?? []).filter((f) => inWindow(f.at_pt, a));
  if (!readings.length && !frames.length) return <Pill answer={null} />;

  const na = readings.filter((r) => r.na).length;
  const queues = readings.flatMap((r) => (r.queue_min === null ? [] : [r.queue_min]));
  const totals = readings.flatMap((r) => (r.total_min === null ? [] : [r.total_min]));
  const noTraffic = readings.length > 0 && na === readings.length;
  const byCamera = new Map<string, typeof frames>();
  frames.forEach((f) => byCamera.set(f.camera, [...(byCamera.get(f.camera) ?? []), f]));

  return (
    <>
      {readings.length > 0 && (
        <>
          <span className={`${styles.pill} ${noTraffic ? styles.no : styles.yes}`}>
            {noTraffic ? "no truck traffic recorded" : `queue up to ${mins(Math.max(...queues, 0))}`}
          </span>
          <div className={styles.detail}>
            {readings.length} turn-time reading{readings.length > 1 ? "s" : ""}
            {totals.length > 0 && <>, whole visit up to {mins(Math.max(...totals))}</>}
            {na > 0 && (
              <>
                {" "}· <b>{na} read N/A</b> (fewer than 20 trucks in the hour)
                {noTraffic && d.answers.gate_scheduled_open && <> while the gate was scheduled open</>}
              </>
            )}
          </div>
          <EvidenceList ids={[readings[0].capture_id, readings[readings.length - 1].capture_id]} caps={caps} />
        </>
      )}
      {frames.length > 0 && (
        <details className={styles.detail}>
          <summary>
            {frames.length} gate camera image{frames.length > 1 ? "s" : ""}
          </summary>
          {[...byCamera.entries()].map(([camera, fs]) => (
            <div key={camera}>
              {camera}:{" "}
              {fs.map((f, i) => (
                <span key={f.capture_id}>
                  {i > 0 && " "}
                  <a href={`/raw/${f.hash}`} target="_blank" rel="noreferrer" title={`capture #${f.capture_id} · ${f.hash.slice(0, 12)}`}>
                    {f.at_pt}
                  </a>
                </span>
              ))}
            </div>
          ))}
        </details>
      )}
    </>
  );
}

function SlotsCell({ d, caps }: { d: Day; caps: Record<number, Evidence> }) {
  const s = d.slots;
  if (!s || !s.queries.length) return <Pill answer={null} text="no channel" />;
  return (
    <>
      <Pill answer={d.answers.appointments_available} mock={s.mock} />
      <div className={styles.detail}>
        {s.queries.map((q, i) => (
          <span key={i}>
            {i > 0 && " · "}
            {q.query.trade_type} {q.query.pick_drop} {q.query.equipment}
            {q.query.line ? ` ${q.query.line}` : ""}: {q.samples_with_slot_that_day}/{q.samples} checks found a slot
          </span>
        ))}
      </div>
      <EvidenceList ids={s.queries.flatMap((q) => q.evidence)} caps={caps} />
    </>
  );
}

export default function Corroboration({ exhibit: x, dates }: { exhibit: Exhibit; dates: CheckDate[] }) {
  const caps = Object.fromEntries(x.captures.map((c) => [c.capture_id, c])) as Record<number, Evidence>;
  const byDate = Object.fromEntries(x.days.map((d) => [d.date, d]));
  const f = x.filters;
  // The appointment column exists only while the (mock) slots channel is switched on in the archive.
  const showSlots = x.channels.some((c) => c.channel === "slots");

  return (
    <section className={styles.exhibit}>
      <h2>
        {x.terminal}
        {f.line || f.equipment ? ` · ${[f.line, f.equipment].filter(Boolean).join(" ")}` : ""} · {dates.length} day
        {dates.length === 1 ? "" : "s"}
      </h2>
      <div className={styles.sub}>What the terminal had published about itself on each day. Checked {fmt(x.generated_at_utc)} UTC.</div>

      <table className={styles.days}>
        <thead>
          <tr>
            <th>
              Day <Info info={INFO.dates} />
            </th>
            <th>
              Gate scheduled open? <Info info={INFO.gate} />
            </th>
            <th>
              Empties accepted for your box? <Info info={INFO.empties} />
            </th>
            <th>
              Closure or restriction noticed? <Info info={INFO.notices} />
            </th>
            <th>
              At the gate <Info info={INFO.atGate} />
            </th>
            {showSlots && (
              <th>
                Appointment available? <Info info={INFO.slots} />
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {dates.map((a, i) => {
            const d = byDate[a.date];
            return (
              <tr key={i}>
                <td className={styles.date}>
                  {a.date}
                  <small>
                    {d?.weekday ?? ""} · {a.from || a.to ? `${a.from || "…"}–${a.to || "…"}` : "all day"}
                  </small>
                </td>
                {d ? (
                  <>
                    <td><GateCell d={d} caps={caps} /></td>
                    <td><EmptiesCell d={d} caps={caps} /></td>
                    <td><NoticesCell d={d} caps={caps} /></td>
                    <td><AtGateCell d={d} a={a} caps={caps} /></td>
                    {showSlots && <td><SlotsCell d={d} caps={caps} /></td>}
                  </>
                ) : (
                  <td colSpan={showSlots ? 5 : 4}><Pill answer={null} /></td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className={styles.footer}>
        Evidence <Info info={INFO.evidence} /> under each answer is the stored copy it was read from. Times are America/Los_Angeles.{" "}
        {x.caveat}
      </div>
    </section>
  );
}
