import { useMemo } from "react";

const DANGER = [
  "blood",
  "bone",
  "shadow",
  "rot",
  "curse",
  "blade",
  "fire",
  "hollow",
  "watching",
  "teeth",
  "ash",
  "corpse",
  "scream",
];

function escapeReg(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Build regex alternation from tokens (longest first). */
function buildPattern(tokens) {
  const uniq = [...new Set(tokens.filter(Boolean).map((t) => t.trim()).filter(Boolean))];
  uniq.sort((a, b) => b.length - a.length);
  if (!uniq.length) return null;
  const inner = uniq.map(escapeReg).join("|");
  return new RegExp(`(${inner})`, "gi");
}

function mergeHighlights(text, layers) {
  // Simple approach: apply layers sequentially to string by wrapping — for MVP use first match wins via single walk
  if (!text) return null;
  const tokens = [];
  for (const { pattern, className, priority } of layers) {
    if (!pattern) continue;
    const re = new RegExp(pattern.source, pattern.flags);
    let m;
    while ((m = re.exec(text)) !== null) {
      tokens.push({
        start: m.index,
        end: m.index + m[0].length,
        className,
        priority,
      });
      if (m.index === re.lastIndex) re.lastIndex++;
    }
  }
  tokens.sort((a, b) => a.start - b.start || a.priority - b.priority);
  const kept = [];
  for (const t of tokens) {
    if (kept.some((k) => !(t.end <= k.start || t.start >= k.end))) continue;
    kept.push(t);
  }
  kept.sort((a, b) => a.start - b.start);
  const out = [];
  let pos = 0;
  for (const t of kept) {
    if (t.start > pos) out.push(text.slice(pos, t.start));
    out.push(
      <span key={`${t.start}-${t.end}`} className={t.className}>
        {text.slice(t.start, t.end)}
      </span>
    );
    pos = t.end;
  }
  if (pos < text.length) out.push(text.slice(pos));
  return out.length ? out : text;
}

export default function ScenePanel({ scene, notices, state }) {
  const layers = useMemo(() => {
    const npcNames = state?.world?.npcs?.map((n) => n.name).filter(Boolean) ?? [];
    const invNames =
      state?.player?.inventory?.map((s) => s.split(" x")[0].trim()).filter(Boolean) ?? [];
    const dangerPat = buildPattern(DANGER);
    const npcPat = buildPattern(npcNames);
    const invPat = buildPattern(invNames);
    const riskPat = buildPattern(["risk", "doubt", "trap", "hunt", "stalk"]);
    return [
      { pattern: dangerPat, className: "hl-danger", priority: 1 },
      { pattern: npcPat, className: "hl-npc", priority: 2 },
      { pattern: invPat, className: "hl-item", priority: 3 },
      { pattern: riskPat, className: "hl-risk", priority: 4 },
    ].filter((x) => x.pattern);
  }, [state]);

  const body = useMemo(() => mergeHighlights(scene || "", layers), [scene, layers]);

  return (
    <section className="scene-panel">
      <h3 className="panel-title">SCENE</h3>
      <div className="scene-body mono">{body}</div>

      {notices?.length > 0 && (
        <div className="notices">
          <h3 className="panel-title sub">WHAT YOU NOTICE</h3>
          <div className="notice-chips">
            {notices.map((n) => (
              <span key={n} className="chip">
                {n}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
