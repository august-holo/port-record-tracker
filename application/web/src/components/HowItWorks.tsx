import styles from "./Channels.module.css";

/**
 * Plain account of how a fetched page becomes a cell in the table. Static on purpose:
 * it describes the code in src/store.py, src/parse.py and src/api.py, and should be edited
 * when they are. Probably removed once readers stop asking.
 */
export default function HowItWorks() {
  return (
    <details className={styles.details}>
      <summary>How the record is stored and turned into this table</summary>
      <div className={styles.prose}>
        <h3>1. Fetch and keep, unchanged</h3>
        <p>
          On a schedule (every 15 minutes to two hours, depending on the page) a small program requests each page
          exactly as a browser would, identifying itself with a contact email. The response body is written to disk
          as-is, named by its SHA-256 hash (<code>data/raw/8f/8fc336…html</code>), and one row is added to a{" "}
          <code>captures</code> table: which page, the UTC time, the HTTP status, the hash. Rows are only ever
          added; nothing is edited or deleted, and an unchanged page is still recorded so it is provable that the
          page said the same thing at that time. If the fetch fails, the failure is recorded too.
        </p>

        <h3>2. Read facts out of each copy</h3>
        <p>
          A parser per page turns the HTML into rows in a second table, <code>parsed_rows</code>, each tied to the
          capture it came from. This table is derived and can be rebuilt from the raw copies at any time. The kinds
          of row are: a <b>gate day</b> (terminal, date, open or closed, hours), an <b>empty rule</b> (terminal,
          line, container size, drop or pick, accepted yes or no), a <b>notice</b> (a paragraph with an operational
          keyword and any dates it mentions), an <b>export receiving window</b> (vessel, first receiving date,
          cutoff), and a <b>turn-time reading</b> (queue and in-terminal minutes, or N/A). Anything the parser cannot classify is
          kept as a generic table row so nothing is lost. A parser that fails leaves the raw copy untouched and logs
          the error.
        </p>

        <h3>3. Answer the questions for one day</h3>
        <p>For each day you ask about, the table is built like this:</p>
        <ol>
          <li>
            <b>Gate scheduled open?</b> — every gate-day row whose date is that day, from every capture that asserted
            it. If two captures disagree (the terminal changed the schedule), the latest is shown and the change is
            flagged.
          </li>
          <li>
            <b>Empties accepted for your box?</b> — the empty rules from the most recent capture taken on or before
            that day, filtered to your line and size. The answer follows the drop-off rules, since returning an
            empty is a drop; pick-up rules are listed beside it. A rule carried forward from an earlier day says so.
          </li>
          <li>
            <b>Closure or restriction noticed?</b> — notices posted that day, or whose text mentions that day, from the
            port&apos;s bulletin page and the terminal&apos;s own page.
          </li>
          <li>
            <b>At the gate</b> — the port&apos;s truck turn-time readings taken that day, narrowed to your time window if you
            gave one. They do not depend on anyone having posted a notice, so they are the record of closures and
            congestion nobody announced.
          </li>
          <li>
            <b>Appointment available?</b> — not answered yet. The archive has no access to the appointment system,
            so this column is left out.
          </li>
        </ol>
        <p>
          Every cell lists the capture it was read from. A day with no capture for a question says{" "}
          <em>unknown</em>. The archive holds what the terminals published about themselves; it has nothing about
          individual containers.
        </p>

        <h3>What each page actually gives us</h3>
        <p>
          <b>Terminal update pages</b> (NWSA site, one per terminal): a two-week gate-hours table, an
          empty-return matrix by line and size, and notice paragraphs. These feed the first three columns directly.
          Husky and PCT write their empty rules as prose rather than a matrix, so for them the empties column is
          unknown and the rules appear as notices instead.
        </p>
        <p>
          <b>WUT empty receiving</b> (WUT&apos;s own site): a dated yes/no matrix by line and size. Feeds the empties
          column for WUT.
        </p>
        <p>
          <b>NWSA trucker news</b>: dated bulletins. Feeds the notices column for every terminal.
        </p>
        <p>
          <b>Export receiving dates</b> (NWSA and WUT): vessel cutoffs and first-receiving dates. Captured and parsed,
          but not used in this table; they belong to the export side of the story.
        </p>
        <p>
          <b>Truck turn times</b> (NWSA): the port&apos;s Cameras &amp; Truck Turn Times page shows two numbers per
          terminal, queue minutes and in-terminal minutes, averaged over the last hour from RFID tags on the trucks.
          Those numbers are not in the page&apos;s HTML; a script fills them in after the page loads, from a live
          feed. So we read that feed directly, every 15 minutes, and store what it sent exactly as received. It feeds
          the At the gate column. The port reports N/A when fewer than 20 trucks passed in the hour, which it says
          may be attributed to terminal closures and lunch breaks. We also keep a copy of the page itself every two
          hours, because it carries the port&apos;s definitions of those numbers. The webcams on that page are not
          captured.
        </p>
        <p>
          <b>eModal status page</b> (CargoSprint, which operates eModal): the incidents the operator has posted about
          the appointment system every terminal here uses, each with its own start and end time. Feeds the notices
          column for every terminal, and because the times are the operator&apos;s, it also covers days from before
          this archive began. It says when the appointment system was broken. It does not say whether slots were
          available; nothing public does.
        </p>
        <p className={styles.note}>
          Raw copies: click a hash to view a capture with scripts disabled, or ↓ to download the original bytes and
          check them with <code>shasum -a 256</code>.
        </p>
      </div>
    </details>
  );
}
