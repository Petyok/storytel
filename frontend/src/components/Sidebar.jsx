import MiniMap from "./MiniMap.jsx";
import { useI18n } from "../i18n/I18nProvider.jsx";

function QuestBlock({ title, quests, empty }) {
  if (!quests?.length) {
    return (
      <div className="quest-block">
        <h4>{title}</h4>
        <p className="muted small">{empty}</p>
      </div>
    );
  }
  return (
    <div className="quest-block">
      <h4>{title}</h4>
      <ul className="quest-list">
        {quests.map((q) => (
          <li key={q.id ?? q.title}>
            <span className="quest-title">{q.title}</span>
            {q.description && <span className="quest-desc muted small">{q.description}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatMod(n) {
  const v = Number(n) || 0;
  if (v >= 0) return `+${v}`;
  return String(v);
}

/**
 * @param {{ state: any, skillKeys?: string[] }} props
 */
export default function Sidebar({ state, skillKeys = [] }) {
  const { t } = useI18n();
  const inv = state?.player?.inventory ?? [];
  const active = state?.quests?.active ?? [];
  const done = state?.quests?.completed ?? [];
  const map = state?.world?.ascii_map ?? "";
  const skills = state?.player?.skills ?? {};

  return (
    <aside className="sidebar">
      {skillKeys.length > 0 && (
        <>
          <h3 className="panel-title">{t("skillsTitle")}</h3>
          <ul className="skill-list">
            {skillKeys.map((k) => {
              const labelKey = `skill_${k}`;
              const label = t(labelKey) === labelKey ? k : t(labelKey);
              return (
                <li key={k}>
                  <span className="skill-name">{label}</span>
                  <span className="skill-mod mono">{formatMod(skills[k])}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <h3 className="panel-title">{t("inventory")}</h3>
      <ul className="inv-list">
        {inv.length === 0 && <li className="muted small">{t("invEmpty")}</li>}
        {inv.map((line) => (
          <li key={line}>
            <span className="inv-icon" aria-hidden>
              🔑
            </span>
            {line}
          </li>
        ))}
      </ul>

      <QuestBlock title={t("questsActive")} quests={active} empty={t("questsNone")} />
      <QuestBlock title={t("questsDone")} quests={done} empty={t("questsNone")} />

      <h3 className="panel-title">{t("map")}</h3>
      <MiniMap asciiMap={map} />
    </aside>
  );
}
