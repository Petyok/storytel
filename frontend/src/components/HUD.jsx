import { useI18n } from "../i18n/I18nProvider.jsx";

export default function HUD({ player, world }) {
  const { t } = useI18n();
  if (!player || !world) return null;
  return (
    <header className="hud">
      <div className="hud-item hud-hp" title={t("hudHp")}>
        <span className="hud-icon" aria-hidden>
          🩸
        </span>
        <span>
          {t("hudHp")} {player.hp}
        </span>
      </div>
      <div className="hud-item hud-gold" title={t("hudGold")}>
        <span className="hud-icon" aria-hidden>
          ◆
        </span>
        <span>
          {t("hudGold")} {player.gold}
        </span>
      </div>
      <div className="hud-item hud-status" title={t("hudStatus")}>
        <span className="hud-icon" aria-hidden>
          👤
        </span>
        <span>{player.status}</span>
      </div>
      <div className="hud-item hud-loc" title={t("hudLocation")}>
        <span className="muted">@</span> {world.location}
      </div>
      <div className="hud-item hud-time" title={t("hudTime")}>
        <span className="muted">⏱</span> {world.time}
      </div>
      <div className="hud-item hud-danger" title={t("hudDanger")}>
        <span className="hud-icon" aria-hidden>
          ⚠
        </span>
        <span>
          {t("hudDanger")} {world.danger_level}
        </span>
      </div>
    </header>
  );
}
