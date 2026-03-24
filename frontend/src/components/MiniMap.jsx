import { useI18n } from "../i18n/I18nProvider.jsx";

export default function MiniMap({ asciiMap }) {
  const { t } = useI18n();
  if (!asciiMap || !String(asciiMap).trim()) {
    return <pre className="minimap empty">{t("mapEmpty")}</pre>;
  }
  return (
    <>
      <pre className="minimap" aria-label={t("mapAria")}>
        {asciiMap}
      </pre>
      <p className="map-legend muted small">{t("mapLegend")}</p>
    </>
  );
}
