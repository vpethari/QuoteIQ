import { Fragment } from "react";
import {
  displayedProductcode,
  formatQuantity,
  matchWhyHeadline,
  overallPercent,
  percentTone,
  statusBadge,
  statusLabel,
} from "../lib/matchDisplay";
import type { QuoteMatchResult } from "../types/quote";
import { CandidateDetails } from "./CandidateDetails";
import { IconEye, IconInfo } from "./Icons";

export function ResultsTable({
  results,
  expandedRows,
  onToggle,
  onSelectCandidate,
  selectingIndex,
}: {
  results: QuoteMatchResult[];
  expandedRows: Set<number>;
  onToggle: (index: number) => void;
  onSelectCandidate?: (index: number, row: QuoteMatchResult, productcode: string) => void;
  selectingIndex?: number | null;
}) {
  return (
    <section className="table-card" aria-labelledby="table-heading">
      <h2 id="table-heading">Quote Results</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Requested Product</th>
              <th>Qty</th>
              <th>
                <span className="th-with-info">
                  Matched Part Number
                  <span className="info-tip" title="PostgreSQL Productcode as text. Numeric codes are never comma-formatted.">
                    <IconInfo />
                  </span>
                </span>
              </th>
              <th>Matched Description</th>
              <th>Confidence</th>
              <th>Status</th>
              <th>Why</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {results.map((row, index) => {
              const expanded = expandedRows.has(index);
              const badge = statusBadge(row.match_status);
              const requested =
                row.requested_description || row.requested_part_number || "—";
              const actionLabel =
                badge === "REVIEW_REQUIRED"
                  ? expanded
                    ? "Hide review"
                    : "Review Match"
                  : expanded
                    ? "Hide details"
                    : "Show details";
              return (
                <Fragment key={index}>
                  <tr className={expanded ? "is-expanded" : undefined}>
                    <td>
                      <div className="requested">{requested}</div>
                      {badge === "NO_MATCH" ? (
                        <div className="row-note">No matching Atkore part found</div>
                      ) : null}
                      {badge === "REVIEW_REQUIRED" ? (
                        <div className="row-note">REVIEW REQUIRED — {row.candidate_count} possible products</div>
                      ) : null}
                    </td>
                    <td>{formatQuantity(row.quantity)}</td>
                    <td className="part">{displayedProductcode(row)}</td>
                    <td>{row.matched_description || "—"}</td>
                    <td className={`numeric ${percentTone(row.overall_match_score ?? row.matching_percentage)}`}>
                      {overallPercent(row)}
                    </td>
                    <td>
                      <span className={`status ${badge.toLowerCase()}`} title={row.match_status}>
                        {statusLabel(row.match_status)}
                      </span>
                    </td>
                    <td>
                      <div className="why-cell">{matchWhyHeadline(row)}</div>
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          type="button"
                          className="icon-btn"
                          onClick={() => onToggle(index)}
                          aria-expanded={expanded}
                          aria-label={actionLabel}
                          title={actionLabel}
                        >
                          <IconEye />
                        </button>
                      </div>
                    </td>
                  </tr>
                  {expanded ? (
                    <tr className="details">
                      <td colSpan={8}>
                        <CandidateDetails
                          row={row}
                          selecting={selectingIndex === index}
                          onSelectCandidate={
                            onSelectCandidate
                              ? (current, productcode) => onSelectCandidate(index, current, productcode)
                              : undefined
                          }
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
