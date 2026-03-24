import { useState } from "react";
import GameView from "./components/GameView.jsx";
import MainMenu from "./components/MainMenu.jsx";
import { I18nProvider } from "./i18n/I18nProvider.jsx";

const DEFAULT_SESSION = "demo";

function readStoredSession() {
  try {
    return localStorage.getItem("storySession") || DEFAULT_SESSION;
  } catch {
    return DEFAULT_SESSION;
  }
}

function AppShell() {
  const [inGame, setInGame] = useState(false);
  const [sessionId, setSessionId] = useState(readStoredSession);

  if (!inGame) {
    return (
      <MainMenu
        selectedId={sessionId}
        onSelectId={setSessionId}
        onEnterGame={() => setInGame(true)}
      />
    );
  }

  return (
    <GameView
      sessionId={sessionId}
      onSessionIdChange={setSessionId}
      onBackToMenu={() => setInGame(false)}
    />
  );
}

export default function App() {
  return (
    <I18nProvider>
      <AppShell />
    </I18nProvider>
  );
}
