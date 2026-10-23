"use client";

import { useEffect, useState } from "react";
import { fetchSources } from "@/lib/api";
import type { SourceInfo } from "@/lib/types";
import { fmt } from "@/lib/util";
import styles from "./Channels.module.css";

const USED: Record<SourceInfo["channel"], string> = {
  gate: "Gate column",
  empties: "Empties column",
  bulletin: "Notices column",
  turn_time: "At the gate column",
  camera: "At the gate column",
  appointment_system: "Notices column",
  erd: "Not shown: export side, kept for another post",
  slots: "Appointment column (MOCK)",
};

const CHANNEL_LABEL: Record<SourceInfo["channel"], string> = {
  gate: "Gate hours and closures",
  empties: "Empty-return acceptance by line and size",
  bulletin: "Port notices",
  turn_time: "Truck turn times",
  camera: "Gate camera stills",
  appointment_system: "Appointment system outages (eModal status page)",
  erd: "Export receiving windows",
  slots: "Appointment availability",
};

/** A collapsed list of every channel: what it is, who publishes it, where, how often, and whether it is being captured. */
export default function Channels() {
  const [sources, setSources] = useState<SourceInfo[] | null>(null);
  useEffect(() => {
    fetchSources().then((s) => setSources(s.sources)).catch(() => setSources([]));
  }, []);

  return (
    <details className={styles.details}>
      <summary>Where the record comes from</summary>
      {sources === null ? (
        <p className={styles.muted}>Loading…</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Channel</th>
              <th>Terminal</th>
              <th>Published by</th>
              <th>Page</th>
              <th>Captured</th>
              <th>Status</th>
              <th>In this table</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.source_id} className={s.mock ? styles.mock : ""}>
                <td>{CHANNEL_LABEL[s.channel]}{s.mock ? " (MOCK)" : ""}</td>
                <td>{s.terminal ?? "all"}</td>
                <td>{s.publisher}</td>
                <td>
                  {s.mock ? (
                    <span className={styles.muted}>none</span>
                  ) : (
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.url.replace(/^https?:\/\/(www\.)?/, "")}
                    </a>
                  )}
                </td>
                <td>every {s.cadence_minutes} min{s.channel === "camera" ? ", 5 a.m.–7 p.m." : ""}</td>
                <td>
                  {s.captures ? `${s.captures} captures, last ${fmt(s.last)} UTC` : "none yet"}
                  {s.errors ? ` · ${s.errors} errors` : ""}
                </td>
                <td>{USED[s.channel]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}
