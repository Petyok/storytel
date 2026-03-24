import { useCallback, useEffect, useState } from "react";
import { createSession, fetchHealth, fetchSession, fetchSessions, postAction } from "../api/client.js";
import ChoiceList from "./ChoiceList.jsx";
import HUD from "./HUD.jsx";
import LoadingOverlay from "./LoadingOverlay.jsx";
import ScenePanel from "./ScenePanel.jsx";
import Sidebar from "./Sidebar.jsx";
import { useI18n } from "../i18n/I18nProvider.jsx";

const SKILL_KEYS = [
  "athletics",
  "stealth",
  "perception",
  "persuasion",
  "survival",
  "arcana",
  "medicine",
  "insight",
  "intimidation",
  "investigation",
];

/**
 * @param {{
 *   sessionId: string,
 *   onSessionIdChange: (id: string) => void,
 *   onBackToMenu: () => void,
 * }} props
 */
export default function GameView({ sessionId, onSessionIdChange, onBackToMenu }) {
  const { t, lang } = useI18n();
  const [sessions, setSessions] = useState([]);
  const [state, setState] = useState(null);
  const [scene, setScene] = useState("");
  const [choices, setChoices] = useState([]);
  const [notices, setNotices] = useState([]);
  const [busy, setBusy] = useState(false);
  const [busyKind, setBusyKind] = useState(/** @type {'session' | 'action'} */ ("session"));
  const [error, setError] = useState("");
  const [freeDraft, setFreeDraft] = useState("");
  const [lastMeta, setLastMeta] = useState({
    llmOk: true,
    llmFallback: false,
    attempts: 0,
    effects: [],
    lastCheck: null,
  });
  const [llmMaxRetries, setLlmMaxRetries] = useState(/** @type {number | null} */ (null));

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
      setLastMeta({ llmOk: true, llmFallback: false, attempts: 0, effects: [], lastCheck: null });
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const h = await fetchHealth();
        const n = h.llm_max_retries;
        if (!cancelled && typeof n === "number" && n > 0) setLlmMaxRetries(n);
      } catch {
        if (!cancelled) setLlmMaxRetries(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function applyActionResponse(data) {
    setState(data.state);
    setScene(data.scene);
    setChoices(data.choices || []);
    setNotices(data.notices || []);
    const fb = data.llm_fallback === true;
    const ok = data.llm_ok !== false && !fb;
    setLastMeta({
      llmOk: ok,
      llmFallback: fb,
      attempts: data.llm_attempts ?? 0,
      effects: data.effects_applied || [],
      lastCheck: data.last_skill_check || null,
    });
  }

  async function onChoose(choice) {
    setError("");
    setBusyKind("action");
    setBusy(true);
    try {
      const data = await postAction(sessionId, { choice, free_text: freeDraft });
      applyActionResponse(data);
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

  async function onSubmitFree(e) {
    e.preventDefault();
    const text = freeDraft.trim();
    if (!text) return;
    setError("");
    setBusyKind("action");
    setBusy(true);
    try {
      const data = await postAction(sessionId, { choice: "", free_text: text });
      applyActionResponse(data);
      try {
        const lst = await fetchSessions();
        setSessions(lst.sessions || []);
      } catch {
        /* ignore */
      }
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  const effectLine = (lastMeta.effects || []).filter((x) => !String(x).startsWith("check:")).join(", ");

  return (
    <div className="app game-view">
      <LoadingOverlay visible={busy} kind={busyKind} llmMaxRetries={llmMaxRetries} />

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
                    await createSession(v, false, { language: lang });
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
          {lastMeta.attempts >= 1 && (
            <span className="muted" title={t("llmAttempts")}>
              {" "}
              · {t("llmAttempts")}: {lastMeta.attempts}
              {llmMaxRetries != null && llmMaxRetries > 0 && (
                <span className="muted"> / {llmMaxRetries}</span>
              )}
            </span>
          )}
          {effectLine && (
            <span className="muted" title={t("engineEffects")}>
              {" "}
              · {effectLine}
            </span>
          )}
        </div>
      </div>

      {lastMeta.lastCheck && (
        <div className="skill-check-banner muted small mono">{lastMeta.lastCheck}</div>
      )}

      <HUD player={state?.player} world={state?.world} />

      {error && <div className="banner error">{error}</div>}

      <div className="layout">
        <main className="main">
          <ScenePanel scene={scene} notices={notices} state={state} />
          <ChoiceList choices={choices} disabled={busy} onChoose={onChoose} />
          <form className="free-action" onSubmit={onSubmitFree}>
            <label className="free-action-label" htmlFor="free-act">
              {t("freeActionLabel")}
            </label>
            <div className="free-action-row">
              <input
                id="free-act"
                className="free-action-input"
                placeholder={t("freeActionPlaceholder")}
                value={freeDraft}
                disabled={busy}
                onChange={(e) => setFreeDraft(e.target.value)}
              />
              <button type="submit" className="btn" disabled={busy || !freeDraft.trim()}>
                {t("freeActionSubmit")}
              </button>
            </div>
          </form>
        </main>
        <Sidebar state={state} skillKeys={SKILL_KEYS} />
      </div>

      <footer className="footer muted small mono">{t("footer")}</footer>
    </div>
  );
}
