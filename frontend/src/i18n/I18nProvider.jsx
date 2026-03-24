import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { MESSAGES } from "./messages.js";

const STORAGE_KEY = "storyUiLang";

const I18nContext = createContext({
  lang: "en",
  setLang: (_l) => {},
  t: (_k) => "",
});

function readStoredLang() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "ru" || v === "en") return v;
  } catch {
    /* ignore */
  }
  return "en";
}

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(readStoredLang);

  const setLang = useCallback((next) => {
    const l = next === "ru" ? "ru" : "en";
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = lang === "ru" ? "ru" : "en";
    }
  }, [lang]);

  const t = useCallback(
    (key) => {
      const pack = MESSAGES[lang] || MESSAGES.en;
      return pack[key] ?? MESSAGES.en[key] ?? key;
    },
    [lang]
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
