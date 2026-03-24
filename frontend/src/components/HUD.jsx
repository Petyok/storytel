import { useI18n } from "../i18n/I18nProvider.jsx";

export default function HUD({ player, world }) {
  const { t } = useI18n();
  if (!player || !world) return null;
  const statusKey = `status_${String(player.status || "").toLowerCase().replace(/\s+/g, "_")}`;
  const timeKey = `time_${String(world.time || "").toLowerCase().replace(/\s+/g, "_")}`;
  const locationKey = `location_${String(world.location || "").toLowerCase().replace(/\s+/g, "_")}`;
  const localizedStatus = t(statusKey) === statusKey ? player.status : t(statusKey);
  const localizedTime = t(timeKey) === timeKey ? world.time : t(timeKey);
  const localizedLocation = t(locationKey) === locationKey ? world.location : t(locationKey);
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
        <span>{localizedStatus}</span>
      </div>
      <div className="hud-item hud-loc" title={t("hudLocation")}>
        <span className="muted">@</span> {localizedLocation}
      </div>
      <div className="hud-item hud-time" title={t("hudTime")}>
        <span className="muted">⏱</span> {localizedTime}
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
