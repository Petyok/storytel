import { useMemo } from "react";
import { useI18n } from "../i18n/I18nProvider.jsx";

const DANGER_EN = [
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

const DANGER_RU = [
  "кровь",
  "кость",
  "кости",
  "тьма",
  "тень",
  "тени",
  "проклятье",
  "проклятие",
  "нож",
  "клинок",
  "огонь",
  "пламя",
  "крик",
  "вопль",
  "пепел",
  "зола",
  "смерть",
  "мертв",
  "труп",
  "зуб",
  "зубы",
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
  const { lang, t } = useI18n();
  const layers = useMemo(() => {
    const npcNames = state?.world?.npcs?.map((n) => n.name).filter(Boolean) ?? [];
    const invNames =
      state?.player?.inventory?.map((s) => s.split(" x")[0].trim()).filter(Boolean) ?? [];
    const dangerWords = lang === "ru" ? [...DANGER_EN, ...DANGER_RU] : DANGER_EN;
    const dangerPat = buildPattern(dangerWords);
    const npcPat = buildPattern(npcNames);
    const invPat = buildPattern(invNames);
    const riskWords =
      lang === "ru"
        ? ["risk", "doubt", "trap", "hunt", "stalk", "ловушка", "охота", "риск", "сомнен"]
        : ["risk", "doubt", "trap", "hunt", "stalk"];
    const riskPat = buildPattern(riskWords);
    return [
      { pattern: dangerPat, className: "hl-danger", priority: 1 },
      { pattern: npcPat, className: "hl-npc", priority: 2 },
      { pattern: invPat, className: "hl-item", priority: 3 },
      { pattern: riskPat, className: "hl-risk", priority: 4 },
    ].filter((x) => x.pattern);
  }, [state, lang]);

  const body = useMemo(() => mergeHighlights(scene || "", layers), [scene, layers]);

  return (
    <section className="scene-panel">
      <h3 className="panel-title" title={t("scenePanelTip")}>
        {t("scene")}
      </h3>
      <div className="scene-body">{body}</div>

      {notices?.length > 0 && (
        <div className="notices">
          <h3 className="panel-title sub" title={t("whatYouNoticeTip")}>
            {t("whatYouNotice")}
          </h3>
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
