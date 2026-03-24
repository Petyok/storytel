import { useI18n } from "../i18n/I18nProvider.jsx";

/**
 * @param {{
 *   visible: boolean,
 *   kind?: 'session' | 'action',
 *   llmMaxRetries?: number | null,
 * }} props
 */
export default function LoadingOverlay({ visible, kind = "action", llmMaxRetries = null }) {
  const { t } = useI18n();
  if (!visible) return null;

  const message = kind === "session" ? t("loadingSession") : t("loadingTurn");
  const n = typeof llmMaxRetries === "number" && llmMaxRetries > 0 ? llmMaxRetries : null;

  return (
    <div className="loading-overlay" role="status" aria-live="polite" aria-busy="true">
      <div className="loading-card">
        <div className="loading-spinner" aria-hidden />
        <p className="loading-title">{message}</p>
        <p className="loading-sub muted small">{t("loadingShort")}</p>
        {kind === "action" && n != null && (
          <p className="loading-retry-count mono small" title={t("loadingRetryMax", { n })}>
            {t("loadingRetryMax", { n })}
          </p>
        )}
        {kind === "action" && (
          <p className="loading-retry muted small">{t("loadingRetryHint")}</p>
        )}
      </div>
    </div>
  );
}
