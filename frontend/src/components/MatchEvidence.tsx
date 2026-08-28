import { displayedProductcode, formatProductcode, overallPercent, statusBadge, statusLabel } from "../lib/matchDisplay";
import type { QuoteMatchResult } from "../types/quote";

function fieldMark(level: string): string {
  return level === "none" ? "○" : "✓";
}

export function MatchEvidencePanel({ row }: { row: QuoteMatchResult }) {
  const evidence = row.match_evidence;
  const fields = evidence?.fields ?? [
    { field: "Productcode", level: "none", label: "No match", score: 0 },
    { field: "name", level: "none", label: "No match", score: 0 },
    { field: "description", level: "none", label: "No match", score: 0 },
    { field: "description2", level: "none", label: "No match", score: 0 },
  ];
  const headline = evidence?.headline || row.match_reason || "Catalog match";
  const status = evidence?.status_label || statusLabel(row.match_status);
  const part = formatProductcode(evidence?.matched_part_number) || displayedProductcode(row);
  const percent = evidence ? `${Math.round(evidence.overall_percent)}%` : overallPercent(row);

  return (
    <div className="match-evidence">
      <h3>Why this match</h3>
      <div className="evidence-summary">
        <div>
          <span className="evidence-k">Match status</span>
          <span className={`status ${statusBadge(row.match_status).toLowerCase()}`}>{status}</span>
        </div>
        <div>
          <span className="evidence-k">Matched part number</span>
          <span className="part">{part}</span>
        </div>
        <div>
          <span className="evidence-k">Overall confidence</span>
          <span className="numeric">{percent}</span>
        </div>
        <div>
          <span className="evidence-k">Match type</span>
          <span>
            {row.match_type_label
              || (row.selection_type === "USER_SELECTED" ? "User Selected" : row.selection_type === "AUTOMATIC" ? "Automatic" : "—")}
          </span>
        </div>
        <div>
          <span className="evidence-k">Match reason</span>
          <span>{headline}</span>
        </div>
      </div>
      <h3>Match Evidence</h3>
      <ul className="evidence-fields">
        {fields.map((item) => (
          <li key={item.field} className={`evidence-${item.level}`}>
            <span className="evidence-mark" aria-hidden="true">
              {fieldMark(item.level)}
            </span>
            <span>
              {item.field} — {item.label}
            </span>
          </li>
        ))}
      </ul>
      {evidence?.normalized_terms && evidence.normalized_terms.length > 0 ? (
        <p className="hint">Normalized terms: {evidence.normalized_terms.join("; ")}</p>
      ) : null}
      {evidence?.voltage_evidence && evidence.voltage_evidence.length > 0 ? (
        <p className="hint">{evidence.voltage_evidence.join("; ")}</p>
      ) : null}
      {evidence?.numeric_units ? (
        <p className="hint">Numeric/Units: {evidence.numeric_units}</p>
      ) : null}
      {evidence?.candidate_separation ? (
        <p className="hint">Candidate separation: {evidence.candidate_separation}</p>
      ) : null}
      {evidence?.additional_catalog_tokens && evidence.additional_catalog_tokens.length > 0 ? (
        <p className="hint">Additional catalog tokens: {evidence.additional_catalog_tokens.join(", ")}</p>
      ) : null}
    </div>
  );
}
