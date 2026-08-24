import {
  formatOptionalPercent,
  formatQuantity,
  officialPartNumber,
  overallPercent,
  statusBadge,
  statusLabel,
} from "../lib/matchDisplay";
import type { QuoteMatchResult } from "../types/quote";

export function CandidateDetails({ row }: { row: QuoteMatchResult }) {
  const badge = statusBadge(row.match_status);
  const hasCandidates = (row.candidates?.length ?? 0) > 0;

  return (
    <div className="candidate-details">
      <h3>Match Details</h3>
      <dl className="detail-grid">
        <div>
          <dt>Requested Description</dt>
          <dd>{row.requested_description || row.requested_part_number || "—"}</dd>
        </div>
        {row.requested_part_number ? (
          <div>
            <dt>Requested Part Number</dt>
            <dd className="part">{row.requested_part_number}</dd>
          </div>
        ) : null}
        <div>
          <dt>Quantity</dt>
          <dd>{formatQuantity(row.quantity)}</dd>
        </div>
        <div>
          <dt>Matched Part Number</dt>
          <dd className="part">{officialPartNumber(row.matched_salsify_id)}</dd>
        </div>
        <div>
          <dt>Matched Description</dt>
          <dd>{row.matched_description || "—"}</dd>
        </div>
        <div>
          <dt>Part Number Match</dt>
          <dd>{formatOptionalPercent(row.part_number_match_score)}</dd>
        </div>
        <div>
          <dt>Description Match</dt>
          <dd>{formatOptionalPercent(row.description_match_score)}</dd>
        </div>
        <div>
          <dt>Overall Match</dt>
          <dd>{overallPercent(row)}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={`status ${badge.toLowerCase()}`}>{statusLabel(row.match_status)}</span>
          </dd>
        </div>
      </dl>

      {row.match_reason ? (
        <div className="candidate-reason">
          <h3>Explanation</h3>
          <p>{row.match_reason}</p>
        </div>
      ) : null}

      {badge === "REVIEW_REQUIRED" ? (
        <p className="review-callout">Multiple possible matches</p>
      ) : null}

      {badge === "NO_MATCH" ? (
        <p className="nomatch-callout">No matching Atkore part found</p>
      ) : null}

      {hasCandidates ? (
        <>
          <h3>Top Candidates</h3>
          <ul className="candidates">
            {row.candidates.map((candidate) => (
              <li key={candidate.salsify_id || candidate.official_part_number}>
                <div>
                  <div className="part">{officialPartNumber(candidate.salsify_id)}</div>
                  <div className="hint">{candidate.description ?? "—"}</div>
                  {candidate.match_reasons.length > 0 ? (
                    <div className="hint">{candidate.match_reasons.join("; ")}</div>
                  ) : null}
                </div>
                <div className="candidate-score">{Math.round(candidate.score)}%</div>
              </li>
            ))}
          </ul>
        </>
      ) : badge === "NO_MATCH" ? (
        <p className="hint">No catalog candidates were returned for this line.</p>
      ) : null}
    </div>
  );
}
