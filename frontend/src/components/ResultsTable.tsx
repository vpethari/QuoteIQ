import { Fragment } from "react";
import {
  formatOptionalPercent,
  formatQuantity,
  officialPartNumber,
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
}: {
  results: QuoteMatchResult[];
  expandedRows: Set<number>;
  onToggle: (index: number) => void;
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
                  <span className="info-tip" title="Complete Salsify ID, including the NA1- prefix">
                    <IconInfo />
                  </span>
                </span>
              </th>
              <th>Matched Description</th>
              <th>Part Number Match</th>
              <th>Description Match</th>
              <th>Overall Match</th>
              <th>Status</th>
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
                        <div className="row-note">Multiple possible matches</div>
                      ) : null}
                    </td>
                    <td>{formatQuantity(row.quantity)}</td>
                    <td className="part">{officialPartNumber(row.matched_salsify_id)}</td>
                    <td>{row.matched_description || "—"}</td>
                    <td className={`numeric ${percentTone(row.part_number_match_score)}`}>
                      {formatOptionalPercent(row.part_number_match_score)}
                    </td>
                    <td className={`numeric ${percentTone(row.description_match_score)}`}>
                      {formatOptionalPercent(row.description_match_score)}
                    </td>
                    <td className={`numeric ${percentTone(row.overall_match_score ?? row.matching_percentage)}`}>
                      {overallPercent(row)}
                    </td>
                    <td>
                      <span className={`status ${badge.toLowerCase()}`} title={row.match_status}>
                        {statusLabel(row.match_status)}
                      </span>
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
                      <td colSpan={9}>
                        <CandidateDetails row={row} />
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
