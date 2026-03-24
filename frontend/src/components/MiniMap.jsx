export default function MiniMap({ asciiMap }) {
  if (!asciiMap || !String(asciiMap).trim()) {
    return <pre className="minimap empty">(no map)</pre>;
  }
  return (
    <pre className="minimap" aria-label="ASCII map">
      {asciiMap}
    </pre>
  );
}
