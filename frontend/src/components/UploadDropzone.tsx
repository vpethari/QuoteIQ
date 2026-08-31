import { useId } from "react";
import { IconCloud } from "./Icons";

interface Props {
  loading: boolean;
  onFile: (file: File | null, error?: string) => void;
}

export function UploadDropzone({ loading, onFile }: Props) {
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
    if (!name.endsWith(".xlsx") && !name.endsWith(".pdf")) {
      onFile(null, "Only .xlsx Excel or .pdf files are supported.");
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
          accept=".xlsx,.xls,.pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf"
          hidden
          disabled={loading}
          onChange={(event) => acceptFile(event.target.files?.[0])}
        />
        <span className="dropzone-icon">
          <IconCloud size={28} />
        </span>
        <p className="dropzone-title">Drag and drop your Excel or PDF file here</p>
        <p className="hint">or</p>
        <span className="btn-secondary dropzone-browse">Browse Files</span>
        <p className="hint formats">Supported formats: .xlsx, .xls, .pdf</p>
      </label>
    </section>
  );
}
