"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchExhibit, fetchOptions, fetchSources } from "@/lib/api";
import type { CheckDate, Exhibit, Terminal } from "@/lib/types";
import Channels from "./Channels";
import Corroboration from "./Corroboration";
import HowItWorks from "./HowItWorks";
import Info from "./Info";
import { INFO } from "./infoText";
import styles from "./Form.module.css";

const DEFAULT_TERMINALS: Terminal[] = ["T18", "T5", "Husky", "PCT", "WUT"];
const blank = (): CheckDate => ({ date: "", from: "", to: "" });

/** One terminal, one box, some days. Output: what the terminal published about itself on those days. */
export default function ExhibitApp() {
  const [terminals, setTerminals] = useState<Terminal[]>(DEFAULT_TERMINALS);
  const [terminal, setTerminal] = useState<Terminal>("T18");
  const [lines, setLines] = useState<string[]>([]);
  const [sizes, setSizes] = useState<string[]>([]);
  const [line, setLine] = useState("");
  const [equipment, setEquipment] = useState("");
  const [rows, setRows] = useState<CheckDate[]>([blank()]);
  const [windowed, setWindowed] = useState<boolean[]>([false]);
  const [exhibit, setExhibit] = useState<Exhibit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchSources()
      .then((s) => setTerminals(s.terminals))
      .catch((e: Error) => setError(`Archive API unreachable: ${e.message}`));
  }, []);

  // The line and size choices come from what this terminal's own empty-return grid has listed.
  useEffect(() => {
    let alive = true;
    fetchOptions(terminal)
      .then((o) => {
        if (!alive) return;
        setLines(o.lines);
        setSizes(o.equipment);
        setLine((v) => (o.lines.includes(v) ? v : ""));
        setEquipment((v) => (o.equipment.includes(v) ? v : ""));
      })
      .catch(() => {
        if (!alive) return;
        setLines([]);
        setSizes([]);
      });
    return () => {
      alive = false;
    };
  }, [terminal]);

  const dates = useMemo(
    () => rows.filter((r) => r.date).slice().sort((a, b) => (a.date + a.from).localeCompare(b.date + b.from)),
    [rows],
  );

  const update = (i: number, patch: Partial<CheckDate>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const remove = (i: number) => {
    setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : [blank()]));
    setWindowed((ws) => (ws.length > 1 ? ws.filter((_, j) => j !== i) : [false]));
  };
  const add = () => {
    setRows((rs) => [...rs, blank()]);
    setWindowed((ws) => [...ws, false]);
  };
  const openWindow = (i: number) => setWindowed((ws) => ws.map((w, j) => (j === i ? true : w)));
  const closeWindow = (i: number) => {
    setWindowed((ws) => ws.map((w, j) => (j === i ? false : w)));
    update(i, { from: "", to: "" });
  };

  async function check() {
    if (!dates.length) {
      setError("Add at least one date.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const start = dates[0].date;
      const end = dates[dates.length - 1].date;
      setExhibit(await fetchExhibit({ terminal, start, end, line, equipment }));
    } catch (e) {
      setExhibit(null);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          void check();
        }}
      >
        <label>
          <span>
            Terminal <Info info={INFO.terminal} />
          </span>
          <select value={terminal} onChange={(e) => setTerminal(e.target.value as Terminal)}>
            {terminals.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label>
          <span>
            Shipping line <Info info={INFO.box} />
          </span>
          <select value={line} onChange={(e) => setLine(e.target.value)} disabled={!lines.length}>
            <option value="">{lines.length ? "Any line" : "No grid published for this terminal"}</option>
            {lines.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Container size</span>
          <select value={equipment} onChange={(e) => setEquipment(e.target.value)} disabled={!sizes.length}>
            <option value="">{sizes.length ? "Any size" : "No grid published for this terminal"}</option>
            {sizes.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <fieldset className={styles.dates}>
          <legend>
            Days to check <Info info={INFO.dates} />
          </legend>
          {rows.map((r, i) => (
            <div key={i} className={styles.dateRow}>
              <input type="date" value={r.date} onChange={(e) => update(i, { date: e.target.value })} required={i === 0} aria-label="date" />
              {windowed[i] ? (
                <span className={styles.window}>
                  <input type="time" value={r.from} onChange={(e) => update(i, { from: e.target.value })} aria-label="from" />
                  <span className={styles.dash}>to</span>
                  <input type="time" value={r.to} min={r.from || undefined} onChange={(e) => update(i, { to: e.target.value })} aria-label="to" />
                  <button type="button" className={styles.link} onClick={() => closeWindow(i)}>
                    all day instead
                  </button>
                </span>
              ) : (
                <span className={styles.window}>
                  <span className={styles.allDay}>ALL DAY</span>
                  <button type="button" className={styles.link} onClick={() => openWindow(i)}>
                    add time window
                  </button>
                </span>
              )}
              <button type="button" className={styles.remove} onClick={() => remove(i)} aria-label="remove date" title="remove">
                ×
              </button>
            </div>
          ))}
          <button type="button" className={styles.add} onClick={add}>
            + add another day
          </button>
        </fieldset>

        <div className={styles.actions}>
          <button type="submit" disabled={loading || !dates.length}>
            {loading ? "Checking…" : "Check the record"}
          </button>
        </div>
      </form>
      <Channels />
      <HowItWorks />
      {error && <p className={styles.error}>{error}</p>}
      {exhibit && <Corroboration exhibit={exhibit} dates={dates} />}
    </>
  );
}
