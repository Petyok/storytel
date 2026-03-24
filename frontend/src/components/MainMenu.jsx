import { useEffect, useState } from "react";
import { createSession, fetchSessions } from "../api/client.js";
import { useI18n } from "../i18n/I18nProvider.jsx";

/**
 * @param {{
 *   selectedId: string,
 *   onSelectId: (id: string) => void,
 *   onEnterGame: () => void,
 * }} props
 */
export default function MainMenu({ selectedId, onSelectId, onEnterGame }) {
  const { lang, setLang, t } = useI18n();
  const [sessions, setSessions] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [newId, setNewId] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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

  async function handleCreate() {
    const id = newId.trim();
    if (!id) return;
    setError("");
    setBusy(true);
    try {
      await createSession(id, overwrite);
      setNewId("");
      setOverwrite(false);
      await refreshList();
      onSelectId(id);
    } catch (e) {
      const st = /** @type {{ status?: number, message?: string }} */ (e).status;
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

  async function handleEnterGame() {
    const id = selectedId?.trim();
    if (!id) return;
    if (!sessions.includes(id)) {
      setBusy(true);
      setError("");
      try {
        await createSession(id, false);
        await refreshList();
      } catch (e) {
        setError(String(e?.message || e));
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    onEnterGame();
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
            {selectedId && !sessions.includes(selectedId) && (
              <option value={selectedId}>
                {selectedId}
              </option>
            )}
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

        <h2 className="main-menu-section">{t("createSession")}</h2>
        <p className="muted small main-menu-hint">{t("newSessionHint")}</p>
        <div className="main-menu-create">
          <input
            className="main-menu-input"
            placeholder={t("newSessionName")}
            value={newId}
            disabled={busy}
            onChange={(e) => setNewId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
            }}
          />
          <label className="main-menu-check">
            <input
              type="checkbox"
              checked={overwrite}
              disabled={busy}
              onChange={(e) => setOverwrite(e.target.checked)}
            />
            {t("overwrite")}
          </label>
          <button type="button" className="btn" disabled={busy || !newId.trim()} onClick={handleCreate}>
            {busy ? t("creating") : t("createSession")}
          </button>
        </div>

        {error && <div className="banner error main-menu-error">{error}</div>}

        <p className="muted small main-menu-playhint">{t("playHint")}</p>
        <button
          type="button"
          className="btn main-menu-play"
          disabled={busy || !selectedId?.trim()}
          onClick={handleEnterGame}
        >
          {t("enterGame")}
        </button>
      </div>
    </div>
  );
}
