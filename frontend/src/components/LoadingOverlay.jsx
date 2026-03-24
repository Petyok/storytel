import { useI18n } from "../i18n/I18nProvider.jsx";

/**
 * @param {{ visible: boolean, kind?: 'session' | 'action' }} props
 */
export default function LoadingOverlay({ visible, kind = "action" }) {
  const { t } = useI18n();
  if (!visible) return null;

  const message = kind === "session" ? t("loadingSession") : t("loadingTurn");

  return (
    <div className="loading-overlay" role="status" aria-live="polite" aria-busy="true">
      <div className="loading-card">
        <div className="loading-spinner" aria-hidden />
        <p className="loading-title">{message}</p>
        <p className="loading-sub muted small">{t("loadingShort")}</p>
      </div>
    </div>
  );
}
