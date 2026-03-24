import { useCallback, useEffect, useState } from "react";
import { fetchSession, fetchSessions, postAction } from "./api/client.js";
import ChoiceList from "./components/ChoiceList.jsx";
import HUD from "./components/HUD.jsx";
import ScenePanel from "./components/ScenePanel.jsx";
import Sidebar from "./components/Sidebar.jsx";

const DEFAULT_SESSION = "demo";

export default function App() {
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(() => {
    try {
      return localStorage.getItem("storySession") || DEFAULT_SESSION;
    } catch {
      return DEFAULT_SESSION;
    }
  });
  const [state, setState] = useState(null);
  const [scene, setScene] = useState("");
  const [choices, setChoices] = useState([]);
  const [notices, setNotices] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastMeta, setLastMeta] = useState({ llmOk: true, effects: [] });

  const load = useCallback(async (id) => {
    setError("");
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
    fetchSessions()
      .then((r) => setSessions(r.sessions || []))
      .catch(() => setSessions([]));
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
    <div className="app">
      <div className="top-row">
        <div className="session-bar">
          <label className="session-label" htmlFor="sess">
            Session
          </label>
          <select
            id="sess"
            className="session-select"
            value={sessionId}
            disabled={busy}
            onChange={(e) => setSessionId(e.target.value)}
          >
            {!sessions.includes(sessionId) && (
              <option value={sessionId}>
                {sessionId} (current)
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
            placeholder="custom id"
            disabled={busy}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const v = e.currentTarget.value.trim();
                if (v) {
                  setSessionId(v);
                  e.currentTarget.value = "";
                }
              }
            }}
          />
          <button type="button" className="btn ghost" disabled={busy} onClick={() => load(sessionId)}>
            Reload
          </button>
        </div>
        <div className="meta-bar mono small">
          {lastMeta.llmOk ? (
            <span className="ok">LLM ok</span>
          ) : (
            <span className="warn">LLM fallback</span>
          )}
          {lastMeta.effects?.length > 0 && (
            <span className="muted" title="Engine effects">
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

      <footer className="footer muted small mono">
        Auto-saves after each choice · JSON under <code>sessions/&lt;id&gt;/</code>
      </footer>
    </div>
  );
}
