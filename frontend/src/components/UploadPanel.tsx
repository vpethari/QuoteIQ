import { formatFileSize } from "../lib/matchDisplay";
import { AiToggle } from "./AiToggle";

interface Props {
  file: File | null;
  lineCount: number | null;
  loading: boolean;
  useAI: boolean;
  onUseAI: (value: boolean) => void;
  onProcess: () => void;
  onFile: (file: File | null, error?: string) => void;
}

export function UploadPanel({ file, lineCount, loading, useAI, onUseAI, onProcess, onFile }: Props) {
  return (
    <section className="upload-panel" aria-label="Selected file and processing options">
      {file ? (
        <div className="file-meta">
          <span
            className={file.name.toLowerCase().endsWith(".pdf") ? "pdf-icon" : "xlsx-icon"}
            aria-hidden="true"
          />
          <div className="file-copy">
            <p className="filename">{file.name}</p>
            <p className="hint">
              {formatFileSize(file.size)}
              {lineCount !== null ? (
                <span className="file-ok">
                  {" "}
                  ✓ {lineCount} line item{lineCount === 1 ? "" : "s"} detected
                </span>
              ) : null}
            </p>
          </div>
          <button type="button" className="btn-ghost" disabled={loading} onClick={() => onFile(null)}>
            Remove
          </button>
        </div>
      ) : null}
      <div className="upload-actions">
        <AiToggle enabled={useAI} disabled={loading} onChange={onUseAI} />
        <button type="button" className="btn-orange process-btn" disabled={!file || loading} onClick={onProcess}>
          {loading ? "Processing Quote..." : "Process Quote →"}
        </button>
      </div>
    </section>
  );
}
