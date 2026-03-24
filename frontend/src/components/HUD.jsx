export default function HUD({ player, world }) {
  if (!player || !world) return null;
  return (
    <header className="hud">
      <div className="hud-item hud-hp" title="Health">
        <span className="hud-icon" aria-hidden>
          🩸
        </span>
        <span>HP {player.hp}</span>
      </div>
      <div className="hud-item hud-gold" title="Gold">
        <span className="hud-icon" aria-hidden>
          ◆
        </span>
        <span>{player.gold}</span>
      </div>
      <div className="hud-item hud-status" title="Status">
        <span>{player.status}</span>
      </div>
      <div className="hud-item hud-loc" title="Location">
        <span className="muted">@</span> {world.location}
      </div>
      <div className="hud-item hud-time" title="Time">
        <span className="muted">⏱</span> {world.time}
      </div>
      <div className="hud-item hud-danger" title="Danger">
        <span className="hud-icon" aria-hidden>
          ⚠
        </span>
        <span>{world.danger_level}</span>
      </div>
    </header>
  );
}
