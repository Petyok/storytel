export default function ChoiceList({ choices, disabled, onChoose }) {
  if (!choices?.length) {
    return <p className="muted small">No choices yet. Load a session.</p>;
  }
  return (
    <div className="choices">
      <h3 className="panel-title">CHOICES</h3>
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
