import { useCallback, useEffect, useState } from "react";
import { fetchPublicSettings, postTestLlm } from "../api/client.js";
import { useI18n } from "../i18n/I18nProvider.jsx";

/**
 * @param {{ open: boolean, onClose: () => void }} props
 */
export default function ProviderSettingsModal({ open, onClose }) {
  const { t } = useI18n();
  const [settings, setSettings] = useState(/** @type {Record<string, unknown> | null} */ (null));
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  /** @type {null | { ok: boolean, latency_ms: number, llm_provider: string, response_preview?: string, error?: string, detail?: string }} */
  const [testResult, setTestResult] = useState(null);

  const refresh = useCallback(async () => {
    setLoadError("");
    setLoading(true);
    try {
      const s = await fetchPublicSettings();
      setSettings(s);
    } catch (e) {
      setSettings(null);
      setLoadError(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    refresh();
    setTestResult(null);
  }, [open, refresh]);

  async function handleTest() {
    setTestResult(null);
    setTesting(true);
    try {
      const r = await postTestLlm();
      setTestResult(r);
    } catch (e) {
      setTestResult({
        ok: false,
        latency_ms: 0,
        llm_provider: settings?.llm_provider || "?",
        error: "RequestError",
        detail: String(e?.message || e),
      });
    } finally {
      setTesting(false);
    }
  }

  if (!open) return null;

  return (
    <div className="settings-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="settings-modal"
        role="dialog"
        aria-labelledby="settings-modal-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="settings-modal-head">
          <h2 id="settings-modal-title" className="settings-modal-title">
            {t("providerSettingsTitle")}
          </h2>
          <button type="button" className="btn ghost settings-modal-close" onClick={onClose} aria-label={t("close")}>
            ×
          </button>
        </div>
        <p className="muted small settings-modal-intro">{t("providerSettingsIntro")}</p>

        {loading && <p className="muted small">{t("providerSettingsLoading")}</p>}
        {loadError && <div className="banner error settings-modal-banner">{loadError}</div>}

        {settings && !loading && (
          <dl className="settings-dl">
            <dt>{t("providerSettingsProvider")}</dt>
            <dd>{String(settings.llm_provider)}</dd>
            {String(settings.llm_provider) === "openrouter" ? (
              <>
                <dt>{t("providerSettingsOpenRouterModel")}</dt>
                <dd>{settings.openrouter_model || "—"}</dd>
                <dt>{t("providerSettingsOpenRouterBase")}</dt>
                <dd className="settings-dl-mono">{String(settings.openrouter_base_url)}</dd>
                <dt>{t("providerSettingsCredentials")}</dt>
                <dd>
                  {settings.openrouter_ready ? t("providerSettingsReadyYes") : t("providerSettingsReadyNo")}
                </dd>
              </>
            ) : (
              <>
                <dt>{t("providerSettingsLlamaUrl")}</dt>
                <dd className="settings-dl-mono">{String(settings.llama_cpp_url)}</dd>
                <dt>{t("providerSettingsCompletionPath")}</dt>
                <dd className="settings-dl-mono">{String(settings.llama_completion_path)}</dd>
                <dt>{t("providerSettingsApiStyle")}</dt>
                <dd>
                  {String(settings.llm_api_style)} · {String(settings.llm_openai_model)}
                </dd>
                {settings.has_llm_bearer ? (
                  <>
                    <dt>{t("providerSettingsBearer")}</dt>
                    <dd>{t("providerSettingsBearerSet")}</dd>
                  </>
                ) : null}
              </>
            )}
            <dt>{t("providerSettingsTimeout")}</dt>
            <dd>{Number(settings.llm_timeout_sec)}s</dd>
          </dl>
        )}

        <div className="settings-modal-actions">
          <button type="button" className="btn ghost" disabled={loading || testing} onClick={() => refresh()}>
            {t("providerSettingsRefresh")}
          </button>
          <button type="button" className="btn" disabled={loading || testing} onClick={() => handleTest()}>
            {testing ? t("providerSettingsTesting") : t("providerSettingsTest")}
          </button>
        </div>

        {testResult && (
          <div
            className={`settings-test-result ${testResult.ok ? "ok" : "fail"}`}
            role="status"
            aria-live="polite"
          >
            {testResult.ok ? (
              <>
                <strong>{t("providerSettingsTestOk")}</strong>
                <span className="muted small">
                  {" "}
                  ({testResult.latency_ms} ms · {String(testResult.llm_provider)})
                </span>
                {testResult.response_preview ? (
                  <pre className="settings-test-preview">{testResult.response_preview}</pre>
                ) : null}
              </>
            ) : (
              <>
                <strong>{t("providerSettingsTestFail")}</strong>
                <span className="muted small">
                  {" "}
                  ({testResult.latency_ms} ms · {testResult.error || "?"})
                </span>
                {testResult.detail ? <pre className="settings-test-preview">{testResult.detail}</pre> : null}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
