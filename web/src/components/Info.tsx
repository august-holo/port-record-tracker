"use client";

import { useEffect, useRef } from "react";
import styles from "./Info.module.css";

export interface InfoText {
  title: string;
  what: string;
  from: string;
  link?: { href: string; label: string };
}

/** A small ⓘ that opens a native <dialog> saying what a thing is and where it came from. */
export default function Info({ info, label }: { info: InfoText; label?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    const onClick = (e: MouseEvent) => {
      if (e.target === d) d.close();
    };
    d.addEventListener("click", onClick);
    return () => d.removeEventListener("click", onClick);
  }, []);
  return (
    <>
      <button type="button" className={styles.btn} aria-label={`About ${info.title}`} onClick={() => ref.current?.showModal()}>
        {label ?? "i"}
      </button>
      <dialog ref={ref} className={styles.dialog}>
        <div className={styles.body}>
          <h3>{info.title}</h3>
          <p>
            <b>What it is.</b> {info.what}
          </p>
          <p>
            <b>Where it comes from.</b> {info.from}
            {info.link && (
              <>
                {" "}
                <a href={info.link.href} target="_blank" rel="noreferrer">
                  {info.link.label} ↗
                </a>
              </>
            )}
          </p>
          <button type="button" className={styles.close} onClick={() => ref.current?.close()}>
            Close
          </button>
        </div>
      </dialog>
    </>
  );
}
