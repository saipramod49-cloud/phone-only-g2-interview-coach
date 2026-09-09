const LABELS = ["SITUATION", "ACTION", "RESULT", "WHY", "EXAMPLE"];

export function glassesText(answer: string, max = 900): string {
  const cleaned = answer.replace(/\*\*(.*?)\*\*/g, (_, s) => String(s).toUpperCase())
    .replace(/^[-•]\s*/gm, "› ").replace(/\s+\n/g, "\n").trim();
  const emphasized = cleaned.split("\n").map(line => {
    const idx = line.indexOf(":");
    if (idx > 0 && idx < 14) {
      const head = line.slice(0, idx).toUpperCase();
      if (LABELS.includes(head)) return `${head} ·${line.slice(idx + 1)}`;
    }
    return line;
  }).join("\n");
  return emphasized.slice(0, max);
}

export function connectionUrl(httpUrl: string): string {
  const u = new URL(httpUrl.trim());
  if (u.protocol !== "https:" && !/^localhost$|^127\.0\.0\.1$/.test(u.hostname)) throw new Error("Use an HTTPS service URL");
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  u.pathname = "/ws/glasses";
  u.search = "";
  return u.toString();
}
