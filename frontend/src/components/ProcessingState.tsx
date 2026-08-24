export function ProcessingState() {
  return (
    <div className="processing" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <div>
        <p className="processing-title">Uploading...</p>
        <p className="hint">Processing Quote...</p>
        <p className="hint">Analyzing Matches...</p>
      </div>
    </div>
  );
}
