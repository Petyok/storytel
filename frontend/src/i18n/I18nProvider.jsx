import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { MESSAGES } from "./messages.js";

const STORAGE_KEY = "storyUiLang";

/** @param {string} s @param {Record<string, string | number> | undefined} vars */
function formatMsg(s, vars) {
  if (!vars || typeof s !== "string") return s;
  return s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] != null ? String(vars[k]) : `{${k}}`));
}

const I18nContext = createContext({
  lang: "en",
  setLang: (_l) => {},
  /** @type {(k: string, vars?: Record<string, string | number>) => string} */
  t: (_k, _v) => "",
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
    (key, vars) => {
      const pack = MESSAGES[lang] || MESSAGES.en;
      const raw = pack[key] ?? MESSAGES.en[key] ?? key;
      return formatMsg(raw, vars);
    },
    [lang]
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
