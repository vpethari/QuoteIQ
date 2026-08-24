import { useId } from "react";
import { formatFileSize } from "../lib/matchDisplay";
import { AiToggle } from "./AiToggle";
import { IconCloud } from "./Icons";

interface Props {
  file: File | null;
  lineCount: number | null;
  loading: boolean;
  useAI: boolean;
  onUseAI: (value: boolean) => void;
  onProcess: () => void;
  onFile: (file: File | null, error?: string) => void;
}

export function UploadCard({
  file,
  lineCount,
  loading,
  useAI,
  onUseAI,
  onProcess,
  onFile,
}: Props) {
  const inputId = useId();

  function acceptFile(next: File | undefined) {
    if (!next || loading) {
      return;
    }
    const name = next.name.toLowerCase();
    if (name.endsWith(".xls") && !name.endsWith(".xlsx")) {
      onFile(null, "Please upload an .xlsx Excel quote.");
      return;
    }
    if (!name.endsWith(".xlsx")) {
      onFile(null, "Only .xlsx Excel files are supported.");
      return;
    }
    onFile(next);
  }

  return (
    <section id="upload" className="upload-card" aria-labelledby="upload-heading">
      <h2 id="upload-heading">Upload a Quote</h2>
      <label
        className={`dropzone${loading ? " is-disabled" : ""}`}
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
        }}
        onDrop={(event) => {
          event.preventDefault();
          acceptFile(event.dataTransfer.files[0]);
        }}
      >
        <input
          id={inputId}
          type="file"
          accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          hidden
          disabled={loading}
          onChange={(event) => acceptFile(event.target.files?.[0])}
        />
        <span className="dropzone-icon">
          <IconCloud />
        </span>
        <p className="dropzone-title">Drag and drop your Excel file here</p>
        <p className="hint">or</p>
        <span className="btn-secondary dropzone-browse">Browse Files</span>
        <p className="hint formats">Supported formats: .xlsx, .xls</p>
      </label>
      {file ? (
        <div className="file-meta">
          <span className="xlsx-icon" aria-hidden="true" />
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
