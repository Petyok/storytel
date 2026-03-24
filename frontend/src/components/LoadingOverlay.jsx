import { useI18n } from "../i18n/I18nProvider.jsx";

/**
 * @param {{
 *   visible: boolean,
 *   kind?: 'session' | 'action',
 *   llmMaxRetries?: number | null,
 *   liveAttempt?: { current: number, max: number, wave: number, maxWaves: number } | null,
 * }} props
 */
export default function LoadingOverlay({ visible, kind = "action", llmMaxRetries = null, liveAttempt = null }) {
  const { t } = useI18n();
  if (!visible) return null;

  const message = kind === "session" ? t("loadingSession") : t("loadingTurn");
  const n = typeof llmMaxRetries === "number" && llmMaxRetries > 0 ? llmMaxRetries : null;
  const la = liveAttempt;

  return (
    <div className="loading-overlay" role="status" aria-live="polite" aria-busy="true">
      <div className="loading-card">
        <div className="loading-spinner" aria-hidden />
        <p className="loading-title">{message}</p>
        <p className="loading-sub muted small">{t("loadingShort")}</p>
        {kind === "action" && la != null && (
          <p className="loading-retry-count mono" aria-live="polite">
            {t("loadingAttempt", {
              cur: la.current,
              max: la.max,
              wave: la.wave,
              wmax: la.maxWaves,
            })}
          </p>
        )}
        {kind === "action" && la == null && <p className="loading-prepare muted small">{t("loadingPreparing")}</p>}
        {kind === "action" && la == null && n != null && (
          <p className="loading-retry-count mono small muted" title={t("loadingRetryMax", { n })}>
            {t("loadingRetryMax", { n })}
          </p>
        )}
        {kind === "action" && <p className="loading-retry muted small">{t("loadingRetryHint")}</p>}
      </div>
    </div>
  );
}
