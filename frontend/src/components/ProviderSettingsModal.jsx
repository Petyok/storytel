import { useEffect, useState } from "react";
import { fetchProviderSettings, postTestLlm, saveProviderSettings } from "../api/client.js";
import { useI18n } from "../i18n/I18nProvider.jsx";

const DEFAULT_FORM = {
  llm_provider: "local",
  llama_cpp_url: "",
  llama_completion_path: "/v1/completions",
  llm_api_style: "openai_completions",
  llm_openai_model: "",
  llm_api_key: "",
  llm_timeout_sec: "120",
  openrouter_api_key: "",
  openrouter_base_url: "https://openrouter.ai/api/v1",
  openrouter_model: "",
  openrouter_image_model: "",
  openrouter_http_referer: "",
  openrouter_app_title: "Storytel",
  openrouter_cache_enabled: true,
  openrouter_cache_ttl_sec: "1800",
};

function normalizeSettings(data = {}) {
  return {
    llm_provider: data.llm_provider || "local",
    llama_cpp_url: data.llama_cpp_url || "",
    llama_completion_path: data.llama_completion_path || "/v1/completions",
    llm_api_style: data.llm_api_style || "openai_completions",
    llm_openai_model: data.llm_openai_model || "",
    llm_api_key: data.llm_api_key || "",
    llm_timeout_sec: String(data.llm_timeout_sec ?? DEFAULT_FORM.llm_timeout_sec),
    openrouter_api_key: data.openrouter_api_key || "",
    openrouter_base_url: data.openrouter_base_url || "https://openrouter.ai/api/v1",
    openrouter_model: data.openrouter_model || "",
    openrouter_image_model: data.openrouter_image_model || "",
    openrouter_http_referer: data.openrouter_http_referer || "",
    openrouter_app_title: data.openrouter_app_title || "Storytel",
    openrouter_cache_enabled: data.openrouter_cache_enabled !== false,
    openrouter_cache_ttl_sec: String(data.openrouter_cache_ttl_sec ?? DEFAULT_FORM.openrouter_cache_ttl_sec),
  };
}

function toPayload(form) {
  return {
    llm_provider: form.llm_provider,
    llama_cpp_url: form.llama_cpp_url.trim(),
    llama_completion_path: form.llama_completion_path.trim(),
    llm_api_style: form.llm_api_style,
    llm_openai_model: form.llm_openai_model.trim(),
    llm_api_key: form.llm_api_key.trim(),
    llm_timeout_sec: Math.max(1, Number(form.llm_timeout_sec || 120) || 120),
    openrouter_api_key: form.openrouter_api_key.trim(),
    openrouter_base_url: form.openrouter_base_url.trim(),
    openrouter_model: form.openrouter_model.trim(),
    openrouter_image_model: form.openrouter_image_model.trim(),
    openrouter_http_referer: form.openrouter_http_referer.trim(),
    openrouter_app_title: form.openrouter_app_title.trim(),
    openrouter_cache_enabled: form.openrouter_cache_enabled === true,
    openrouter_cache_ttl_sec: Math.max(0, Number(form.openrouter_cache_ttl_sec || 0) || 0),
  };
}

function readinessText(ok, positive, negative) {
  return ok ? positive : negative;
}

export default function ProviderSettingsModal({ open, onClose }) {
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");
  const [savedBanner, setSavedBanner] = useState("");
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    if (!open) return undefined;

    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");
      setSavedBanner("");
      try {
        const data = await fetchProviderSettings();
        if (cancelled) return;
        setSettings(data);
        setForm(normalizeSettings(data));
      } catch (e) {
        if (!cancelled) setError(String(e.message || e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();

    function onKeyDown(e) {
      if (e.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      cancelled = true;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, open]);

  if (!open) return null;

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function reload() {
    setLoading(true);
    setError("");
    setSavedBanner("");
    try {
      const data = await fetchProviderSettings();
      setSettings(data);
      setForm(normalizeSettings(data));
      setTestResult(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setSavedBanner("");
    try {
      const saved = await saveProviderSettings(toPayload(form));
      setSettings(saved);
      setForm(normalizeSettings(saved));
      setSavedBanner(t("providerSettingsSaved"));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setError("");
    setTestResult(null);
    try {
      const result = await postTestLlm(toPayload(form));
      setTestResult(result);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setTesting(false);
    }
  }

  const currentProvider = form.llm_provider === "openrouter" ? "openrouter" : "local";
  const openrouterReady = settings?.openrouter_ready === true;
  const openrouterImageReady = settings?.openrouter_image_ready === true;

  return (
    <div className="settings-modal-backdrop" onClick={onClose}>
      <div
        className="settings-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="provider-settings-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="settings-modal-head">
          <h2 id="provider-settings-title" className="settings-modal-title">
            {t("providerSettingsTitle")}
          </h2>
          <button type="button" className="btn ghost settings-modal-close" onClick={onClose} aria-label={t("close")}>
            ×
          </button>
        </div>

        <p className="settings-modal-intro muted small">{t("providerSettingsIntro")}</p>

        {(error || savedBanner) && (
          <div className={`banner ${error ? "error" : ""} settings-modal-banner`}>
            {error || savedBanner}
          </div>
        )}

        {loading ? (
          <p className="muted small">{t("providerSettingsLoading")}</p>
        ) : (
          <>
            <div className="settings-status-grid">
              <div className={`settings-status-pill ${currentProvider === "openrouter" ? "ok" : ""}`}>
                <span>{t("providerSettingsProvider")}</span>
                <strong>{currentProvider === "openrouter" ? t("providerSettingsOpenRouter") : t("providerSettingsLocal")}</strong>
              </div>
              <div className={`settings-status-pill ${openrouterReady ? "ok" : "warn"}`}>
                <span>{t("providerSettingsCredentials")}</span>
                <strong>{readinessText(openrouterReady, t("providerSettingsReadyYes"), t("providerSettingsReadyNo"))}</strong>
              </div>
              <div className={`settings-status-pill ${openrouterImageReady ? "ok" : "warn"}`}>
                <span>{t("providerSettingsImageModel")}</span>
                <strong>{readinessText(openrouterImageReady, t("providerSettingsReadyYes"), t("providerSettingsImageMissing"))}</strong>
              </div>
              <div className={`settings-status-pill ${form.openrouter_cache_enabled ? "ok" : "warn"}`}>
                <span>{t("providerSettingsCache")}</span>
                <strong>{form.openrouter_cache_enabled ? t("providerSettingsCacheOn") : t("providerSettingsCacheOff")}</strong>
              </div>
            </div>

            <div className="settings-modal-actions">
              <button type="button" className="btn ghost" onClick={reload} disabled={loading || saving || testing}>
                {t("providerSettingsRefresh")}
              </button>
              <button type="button" className="btn ghost" onClick={handleTest} disabled={loading || saving || testing}>
                {testing ? t("providerSettingsTesting") : t("providerSettingsTest")}
              </button>
            </div>

            {testResult && (
              <div className={`settings-test-result ${testResult.ok ? "ok" : "fail"}`}>
                <strong>{testResult.ok ? t("providerSettingsTestOk") : t("providerSettingsTestFail")}</strong>
                {typeof testResult.latency_ms === "number" && <span> · {testResult.latency_ms} ms</span>}
                {testResult.response_preview && <pre className="settings-test-preview">{testResult.response_preview}</pre>}
                {testResult.detail && <pre className="settings-test-preview">{testResult.detail}</pre>}
              </div>
            )}

            <form className="settings-form" onSubmit={handleSave}>
              <section className="settings-section">
                <h3 className="settings-section-title">{t("providerSettingsSectionGeneral")}</h3>
                <div className="settings-grid">
                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsProvider")}</span>
                    <select
                      className="settings-input"
                      value={form.llm_provider}
                      onChange={(e) => updateField("llm_provider", e.target.value)}
                      disabled={saving || testing}
                    >
                      <option value="local">{t("providerSettingsLocal")}</option>
                      <option value="openrouter">{t("providerSettingsOpenRouter")}</option>
                    </select>
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsTimeout")}</span>
                    <input
                      className="settings-input"
                      type="number"
                      min="1"
                      max="600"
                      value={form.llm_timeout_sec}
                      onChange={(e) => updateField("llm_timeout_sec", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>
                </div>
              </section>

              <section className="settings-section">
                <h3 className="settings-section-title">{t("providerSettingsSectionLocal")}</h3>
                <div className="settings-grid">
                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsLlamaUrl")}</span>
                    <input
                      className="settings-input"
                      value={form.llama_cpp_url}
                      onChange={(e) => updateField("llama_cpp_url", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsCompletionPath")}</span>
                    <input
                      className="settings-input"
                      value={form.llama_completion_path}
                      onChange={(e) => updateField("llama_completion_path", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsApiStyle")}</span>
                    <select
                      className="settings-input"
                      value={form.llm_api_style}
                      onChange={(e) => updateField("llm_api_style", e.target.value)}
                      disabled={saving || testing}
                    >
                      <option value="openai_completions">openai_completions</option>
                      <option value="native">native</option>
                    </select>
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsLocalModelId")}</span>
                    <input
                      className="settings-input"
                      value={form.llm_openai_model}
                      onChange={(e) => updateField("llm_openai_model", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsBearer")}</span>
                    <input
                      className="settings-input"
                      type="password"
                      value={form.llm_api_key}
                      onChange={(e) => updateField("llm_api_key", e.target.value)}
                      disabled={saving || testing}
                    />
                    <span className="settings-help muted small">
                      {settings?.has_llm_bearer ? t("providerSettingsBearerSet") : t("providerSettingsBearerUnset")}
                    </span>
                  </label>
                </div>
              </section>

              <section className="settings-section">
                <h3 className="settings-section-title">{t("providerSettingsSectionOpenRouter")}</h3>
                <div className="settings-grid">
                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsApiKey")}</span>
                    <input
                      className="settings-input"
                      type="password"
                      value={form.openrouter_api_key}
                      onChange={(e) => updateField("openrouter_api_key", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsOpenRouterBase")}</span>
                    <input
                      className="settings-input"
                      value={form.openrouter_base_url}
                      onChange={(e) => updateField("openrouter_base_url", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsOpenRouterModel")}</span>
                    <input
                      className="settings-input"
                      value={form.openrouter_model}
                      onChange={(e) => updateField("openrouter_model", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsImageModel")}</span>
                    <input
                      className="settings-input"
                      value={form.openrouter_image_model}
                      onChange={(e) => updateField("openrouter_image_model", e.target.value)}
                      disabled={saving || testing}
                    />
                    <span className="settings-help muted small">{t("providerSettingsImageModelHint")}</span>
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsReferer")}</span>
                    <input
                      className="settings-input"
                      value={form.openrouter_http_referer}
                      onChange={(e) => updateField("openrouter_http_referer", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsAppTitle")}</span>
                    <input
                      className="settings-input"
                      value={form.openrouter_app_title}
                      onChange={(e) => updateField("openrouter_app_title", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>

                  <label className="settings-checkbox">
                    <input
                      type="checkbox"
                      checked={form.openrouter_cache_enabled}
                      onChange={(e) => updateField("openrouter_cache_enabled", e.target.checked)}
                      disabled={saving || testing}
                    />
                    <span>
                      <strong>{t("providerSettingsCacheEnabled")}</strong>
                      <span className="settings-help muted small">{t("providerSettingsCacheHint")}</span>
                    </span>
                  </label>

                  <label className="settings-field">
                    <span className="settings-label">{t("providerSettingsCacheTtl")}</span>
                    <input
                      className="settings-input"
                      type="number"
                      min="0"
                      max="86400"
                      value={form.openrouter_cache_ttl_sec}
                      onChange={(e) => updateField("openrouter_cache_ttl_sec", e.target.value)}
                      disabled={saving || testing}
                    />
                  </label>
                </div>
              </section>

              <div className="settings-form-actions">
                <button type="submit" className="btn" disabled={loading || saving || testing}>
                  {saving ? t("providerSettingsSaving") : t("providerSettingsSave")}
                </button>
                <button type="button" className="btn ghost" onClick={onClose} disabled={saving}>
                  {t("close")}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
