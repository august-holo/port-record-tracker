export const fmt = (s: string | null | undefined) => (s ? s.replace("T", " ").slice(0, 16) : "");
