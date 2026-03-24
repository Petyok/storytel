/**
 * Tooltip text for engine `effects_applied` tags (title=…).
 * @param {string} raw
 * @param {(k: string) => string} t
 */
export function tooltipForEngineEffect(raw, t) {
  const s = String(raw).trim();
  if (!s) return "";

  if (s.startsWith("check:")) return t("effectCheck");
  if (s === "turn+1") return t("effectTurn1");
  if (s === "time_tick") return t("effectTimeTick");
  if (s === "danger_tick") return t("effectDangerTick");

  if (s.startsWith("danger+")) return t("effectDangerPlus");
  if (s.startsWith("danger-")) return t("effectDangerMinus");
  if (s.startsWith("time+")) return t("effectTimePlus");
  if (s.startsWith("hp+") || s.startsWith("hp-")) return t("effectHp");
  if (s.startsWith("gold+") || s.startsWith("gold-")) return t("effectGold");
  if (s.startsWith("flag:")) return t("effectFlag");
  if (s.startsWith("item+:") || s.startsWith("item-:")) return t("effectItem");
  if (s.startsWith("trust:")) return t("effectTrust");
  if (s.startsWith("quest+:")) return t("effectQuestAdd");
  if (s.startsWith("quest~:")) return t("effectQuestUpdate");

  return t("effectUnknown");
}
