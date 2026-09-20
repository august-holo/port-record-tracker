import type { InfoText } from "./Info";

const NWSA = "https://www.nwseaportalliance.com";

export const INFO: Record<string, InfoText> = {
  tool: {
    title: "What this tool does",
    what:
      "Pick a terminal, your box, and the days on the invoice. For each day, the tool shows what the terminal itself had published about its own state, from copies saved at the time: whether the gate was scheduled open, whether it was accepting your line's empties, what notices were in force, and (once the channel exists) whether appointments were available. It does nothing else.",
    from:
      "Public pages of the Northwest Seaport Alliance and the terminal operators, fetched on a schedule, stored unchanged with a UTC timestamp and a SHA-256 hash, and never overwritten. The tool holds what the terminals published about themselves; it has no per-container data.",
  },
  terminal: {
    title: "Terminal",
    what: "The terminal named on the invoice, where the box sat or was due back. T18 and T5 are in Seattle; Husky, PCT and WUT are in Tacoma.",
    from: "The list of NWSA international container terminals.",
    link: { href: `${NWSA}/cargo-operations/terminals`, label: "NWSA terminals" },
  },
  box: {
    title: "Shipping line and container size",
    what:
      "The line (SCAC code, e.g. HLC for Hapag-Lloyd) and the size/type (e.g. 40HC) of your box. Terminals publish empty-return acceptance as a grid by line and size, so these pick the one cell that applies to you. 'Any' shows the whole grid.",
    from:
      "The choices are exactly the lines and sizes this terminal's own empty-return grid has listed in the archive's captures. Husky and PCT publish rules as prose rather than a grid, so they offer no choices.",
  },
  dates: {
    title: "Days to check",
    what:
      "The days you want the record for, usually the days a demurrage or detention invoice is charging. Narrow a day to a time window if it matters; leave it all day otherwise. The tool looks up what the terminal had published for each day.",
    from: "The invoice's free-time and charge dates, or your own records.",
  },
  gate: {
    title: "Gate scheduled open?",
    what:
      "Whether the terminal's own update page listed its gate as open or closed for that date, and the hours shown. A scheduled closure is the plainest reason a box could not move.",
    from: "The terminal's update page on the NWSA site, captured every two hours. Each capture is stored with its time and hash; the ones cited are listed under the answer.",
    link: { href: `${NWSA}/cargo-operations/terminals`, label: "terminal update pages" },
  },
  empties: {
    title: "Empties accepted for your box?",
    what:
      "Whether the terminal's published empty-return grid showed your line and size as accepted, for dropping off (returning) and picking up. 'Refused' means the terminal itself said it was not taking that box that day. If there is no capture from the day itself, the most recent earlier capture is shown and labelled as such.",
    from: "The empty-return table on the terminal's update page, and Washington United Terminals' own empty-receiving page, captured every two hours.",
    link: { href: "https://www.uswut.com/schedule/empty-receiving/", label: "WUT empty receiving" },
  },
  notices: {
    title: "Closure or restriction noticed?",
    what:
      "Port bulletins and terminal notices that mention that date: unscheduled closures, blanket 'not accepting empties' notices, appointment changes. These are the port's own dated statements.",
    from: "NWSA trucker news and the notice paragraphs on each terminal's update page, captured hourly to two-hourly.",
    link: { href: `${NWSA}/cargo-operations/trucker-resources/trucker-news-updates`, label: "NWSA trucker news" },
  },
  slots: {
    title: "Appointment available?",
    what:
      "Whether the appointment system returned any bookable time slot for this kind of move at this terminal on that day. This is the fact that decided the one litigated appointment case, and it is the one channel this archive cannot yet capture.",
    from:
      "MOCK. Until the archive has access to eModal's appointments API, this column is filled with synthetic data that follows the shape of the real API response. It is labelled MOCK everywhere it appears and must not be cited.",
  },
  evidence: {
    title: "Evidence",
    what:
      "The stored copies the answer was read from: the capture number, the time it was fetched (Pacific), and the first characters of its SHA-256 hash. The hash link shows the page as captured (scripts disabled); the arrow downloads the original file, byte for byte.",
    from: "The archive's own store. Run sha256 on the downloaded file: it must equal the full hash, which proves the file is unchanged since capture.",
  },
  unknown: {
    title: "Unknown",
    what: "The archive has no capture for that day and that question. It means the record is missing, not that nothing was wrong.",
    from: "A gap in capture coverage: the archive started later, a page was unreachable, or the terminal did not publish that fact.",
  },
};
