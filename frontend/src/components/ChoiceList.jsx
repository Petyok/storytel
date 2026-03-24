import { useI18n } from "../i18n/I18nProvider.jsx";

export default function ChoiceList({ choices, disabled, onChoose }) {
  const { t } = useI18n();
  if (!choices?.length) {
    return <p className="muted small">{t("noChoices")}</p>;
  }
  return (
    <div className="choices">
      <h3 className="panel-title" title={t("choicesTip")}>
        {t("choices")}
      </h3>
      <div className="choice-grid">
        {choices.map((c, i) => (
          <button
            key={`${i}-${c.slice(0, 24)}`}
            type="button"
            className="choice-btn"
            disabled={disabled}
            onClick={() => onChoose(c)}
          >
            <span className="choice-idx">{i + 1}</span>
            {c}
          </button>
        ))}
      </div>
    </div>
  );
}
