import ExhibitApp from "@/components/ExhibitApp";
import Info from "@/components/Info";
import { INFO } from "@/components/infoText";
import styles from "./page.module.css";

export default function Page() {
  return (
    <>
      <header className={styles.header}>
        <div className={styles.kicker}>Seattle–Tacoma · public record</div>
        <h1>
          Terminal State Archive <Info info={INFO.tool} />
        </h1>
        <p>
          Pick a terminal, your box, and the days on the invoice. This shows what the terminal itself had published
          about its state on those days, from copies saved at the time. Unknown means no saved copy, not that nothing
          was wrong.
        </p>
      </header>
      <main className={styles.main}>
        <ExhibitApp />
      </main>
    </>
  );
}
