import { useCallback, useEffect, useState } from "react";
import { createSession, fetchSession, fetchSessions, postAction } from "../api/client.js";
import ChoiceList from "./ChoiceList.jsx";
import HUD from "./HUD.jsx";
import LoadingOverlay from "./LoadingOverlay.jsx";
import ScenePanel from "./ScenePanel.jsx";
import Sidebar from "./Sidebar.jsx";
import { useI18n } from "../i18n/I18nProvider.jsx";

/**
 * @param {{
 *   sessionId: string,
 *   onSessionIdChange: (id: string) => void,
 *   onBackToMenu: () => void,
 * }} props
 */
export default function GameView({ sessionId, onSessionIdChange, onBackToMenu }) {
  const { t } = useI18n();
  const [sessions, setSessions] = useState([]);
  const [state, setState] = useState(null);
  const [scene, setScene] = useState("");
  const [choices, setChoices] = useState([]);
  const [notices, setNotices] = useState([]);
  const [busy, setBusy] = useState(false);
  const [busyKind, setBusyKind] = useState(/** @type {'session' | 'action'} */ ("session"));
  const [error, setError] = useState("");
  const [lastMeta, setLastMeta] = useState({ llmOk: true, effects: [] });

  const load = useCallback(async (id) => {
    setError("");
    setBusyKind("session");
    setBusy(true);
    try {
      const data = await fetchSession(id);
      setState(data.state);
      setScene(data.last_scene || "");
      setChoices(data.choices || []);
      setNotices(data.notices || []);
      setLastMeta({ llmOk: true, effects: [] });
      try {
        const lst = await fetchSessions();
        setSessions(lst.sessions || []);
      } catch {
        /* ignore */
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem("storySession", sessionId);
    } catch {
      /* ignore */
    }
    load(sessionId);
  }, [sessionId, load]);

  async function onChoose(choice) {
    setError("");
    setBusyKind("action");
    setBusy(true);
    try {
      const data = await postAction(sessionId, choice);
      setState(data.state);
      setScene(data.scene);
      setChoices(data.choices || []);
      setNotices(data.notices || []);
      setLastMeta({ llmOk: data.llm_ok !== false, effects: data.effects_applied || [] });
      try {
        const lst = await fetchSessions();
        setSessions(lst.sessions || []);
      } catch {
        /* ignore */
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app game-view">
      <LoadingOverlay visible={busy} kind={busyKind} />

      <div className="top-row">
        <div className="session-bar">
          <button type="button" className="btn ghost back-menu-btn" disabled={busy} onClick={onBackToMenu}>
            {t("backToMenu")}
          </button>
          <label className="session-label" htmlFor="sess">
            {t("session")}
          </label>
          <select
            id="sess"
            className="session-select"
            value={sessionId}
            disabled={busy}
            onChange={(e) => onSessionIdChange(e.target.value)}
          >
            {!sessions.includes(sessionId) && (
              <option value={sessionId}>
                {sessionId} ({t("sessionCurrent")})
              </option>
            )}
            {sessions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <input
            className="session-input"
            placeholder={t("customIdPlaceholder")}
            disabled={busy}
            onKeyDown={async (e) => {
              if (e.key === "Enter") {
                const v = e.currentTarget.value.trim();
                if (v) {
                  setBusyKind("session");
                  setBusy(true);
                  setError("");
                  try {
                    await createSession(v, false);
                    onSessionIdChange(v);
                  } catch (err) {
                    setError(String(err?.message || err));
                  } finally {
                    setBusy(false);
                  }
                }
                e.currentTarget.value = "";
              }
            }}
          />
          <button type="button" className="btn ghost" disabled={busy} onClick={() => load(sessionId)}>
            {t("reload")}
          </button>
        </div>
        <div className="meta-bar mono small">
          {lastMeta.llmOk ? <span className="ok">{t("llmOk")}</span> : <span className="warn">{t("llmFallback")}</span>}
          {lastMeta.effects?.length > 0 && (
            <span className="muted" title={t("engineEffects")}>
              {" "}
              · {lastMeta.effects.join(", ")}
            </span>
          )}
        </div>
      </div>

      <HUD player={state?.player} world={state?.world} />

      {error && <div className="banner error">{error}</div>}

      <div className="layout">
        <main className="main">
          <ScenePanel scene={scene} notices={notices} state={state} />
          <ChoiceList choices={choices} disabled={busy} onChoose={onChoose} />
        </main>
        <Sidebar state={state} />
      </div>

      <footer className="footer muted small mono">{t("footer")}</footer>
    </div>
  );
}
