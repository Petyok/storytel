import { useEffect, useState } from "react";
import { createSession, fetchSessions } from "../api/client.js";
import { useI18n } from "../i18n/I18nProvider.jsx";

/**
 * @param {{
 *   selectedId: string,
 *   onSelectId: (id: string) => void,
 *   onStartSession: (id: string) => void,
 * }} props
 */
export default function MainMenu({ selectedId, onSelectId, onStartSession }) {
  const { lang, setLang, t } = useI18n();
  const [sessions, setSessions] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [newId, setNewId] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [playerName, setPlayerName] = useState("");
  const [playerBackstory, setPlayerBackstory] = useState("");
  const [worldLocation, setWorldLocation] = useState("");
  const [worldPremise, setWorldPremise] = useState("");

  const setupPayload = () => ({
    language: lang,
    player: {
      name: playerName.trim() || undefined,
      backstory: playerBackstory.trim() || undefined,
    },
    world: {
      location: worldLocation.trim() || undefined,
      premise: worldPremise.trim() || undefined,
    },
  });

  async function refreshList() {
    setListLoading(true);
    setError("");
    try {
      const r = await fetchSessions();
      setSessions(r.sessions || []);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setListLoading(false);
    }
  }

  useEffect(() => {
    refreshList();
  }, []);

  async function handlePlay() {
    const id = newId.trim() || selectedId.trim();
    if (!id) {
      setError(t("needSessionId"));
      return;
    }
    setError("");
    setBusy(true);
    try {
      const exists = sessions.includes(id);
      if (!exists) {
        await createSession(id, false, setupPayload());
      } else if (overwrite) {
        await createSession(id, true, setupPayload());
      }
      await refreshList();
      onSelectId(id);
      onStartSession(id);
    } catch (e) {
      const st = /** @type {{ status?: number }} */ (e).status;
      const msg = String(e?.message || e);
      if (st === 409 || msg.includes("409") || msg.toLowerCase().includes("already")) {
        setError(t("createError409"));
      } else {
        setError(t("createErrorGeneric") + (msg ? ` (${msg})` : ""));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="main-menu">
      <div className="main-menu-card">
        <h1 className="main-menu-title">{t("menuTitle")}</h1>
        <p className="main-menu-sub muted">{t("menuSubtitle")}</p>

        <div className="main-menu-row">
          <label className="main-menu-label" htmlFor="ui-lang">
            {t("language")}
          </label>
          <select
            id="ui-lang"
            className="session-select"
            value={lang}
            disabled={busy}
            onChange={(e) => setLang(e.target.value)}
          >
            <option value="en">{t("langEn")}</option>
            <option value="ru">{t("langRu")}</option>
          </select>
        </div>

        <h2 className="main-menu-section">{t("yourSessions")}</h2>
        {listLoading ? (
          <p className="muted small">{t("loadingSession")}</p>
        ) : sessions.length === 0 ? (
          <p className="muted small">{t("noSessionsYet")}</p>
        ) : (
          <select
            className="main-menu-select"
            value={selectedId}
            disabled={busy}
            onChange={(e) => onSelectId(e.target.value)}
          >
            {selectedId && !sessions.includes(selectedId) && <option value={selectedId}>{selectedId}</option>}
            {sessions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}

        <div className="main-menu-actions">
          <button type="button" className="btn ghost" disabled={busy} onClick={() => refreshList()}>
            {t("refreshList")}
          </button>
        </div>

        <h2 className="main-menu-section">{t("newGameSection")}</h2>
        <p className="muted small main-menu-hint">{t("newSessionHint")}</p>
        <div className="main-menu-create">
          <label className="main-menu-fieldlabel">{t("newSessionName")}</label>
          <input
            className="main-menu-input"
            placeholder={t("newSessionName")}
            value={newId}
            disabled={busy}
            onChange={(e) => setNewId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handlePlay();
            }}
          />
          <label className="main-menu-fieldlabel">{t("playerName")}</label>
          <input
            className="main-menu-input"
            placeholder={t("playerNamePlaceholder")}
            value={playerName}
            disabled={busy}
            onChange={(e) => setPlayerName(e.target.value)}
          />
          <label className="main-menu-fieldlabel">{t("playerBackstory")}</label>
          <textarea
            className="main-menu-input main-menu-textarea"
            placeholder={t("playerBackstoryPlaceholder")}
            value={playerBackstory}
            disabled={busy}
            onChange={(e) => setPlayerBackstory(e.target.value)}
          />
          <label className="main-menu-fieldlabel">{t("worldLocation")}</label>
          <input
            className="main-menu-input"
            placeholder={t("worldLocationPlaceholder")}
            value={worldLocation}
            disabled={busy}
            onChange={(e) => setWorldLocation(e.target.value)}
          />
          <label className="main-menu-fieldlabel">{t("worldPremise")}</label>
          <textarea
            className="main-menu-input main-menu-textarea"
            placeholder={t("worldPremisePlaceholder")}
            value={worldPremise}
            disabled={busy}
            onChange={(e) => setWorldPremise(e.target.value)}
          />
          <label className="main-menu-check">
            <input type="checkbox" checked={overwrite} disabled={busy} onChange={(e) => setOverwrite(e.target.checked)} />
            {t("overwrite")}
          </label>
        </div>

        {error && <div className="banner error main-menu-error">{error}</div>}

        <p className="muted small main-menu-playhint">{t("playSingleHint")}</p>
        <button type="button" className="btn main-menu-play" disabled={busy} onClick={handlePlay}>
          {busy ? t("starting") : t("play")}
        </button>
      </div>
    </div>
  );
}
