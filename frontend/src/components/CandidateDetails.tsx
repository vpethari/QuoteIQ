import {
  atkoreUrlForName,
  candidateProductcode,
  displayedProductcode,
  formatOptionalPercent,
  formatQuantity,
  overallPercent,
  statusBadge,
  statusLabel,
} from "../lib/matchDisplay";
import type { CandidateProduct, QuoteMatchResult } from "../types/quote";
import { AtkoreProductLink } from "./AtkoreProductLink";
import { MatchEvidencePanel } from "./MatchEvidence";

function CandidateAtkoreLink({ candidate }: { candidate: CandidateProduct }) {
  return <AtkoreProductLink url={atkoreUrlForName(candidate.name)} />;
}

function candidateReason(candidate: CandidateProduct): string {
  return (
    candidate.match_reason
    || candidate.match_evidence?.headline
    || candidate.match_reasons?.[0]
    || "Possible catalog match"
  );
}

function candidateName(candidate: CandidateProduct): string {
  return candidate.name || candidate.description || "";
}

export function CandidateDetails({
  row,
  onSelectCandidate,
  selecting,
}: {
  row: QuoteMatchResult;
  onSelectCandidate?: (row: QuoteMatchResult, productcode: string) => void;
  selecting?: boolean;
}) {
  const badge = statusBadge(row.match_status);
  const hasCandidates = (row.candidates?.length ?? 0) > 0;
  const review = badge === "REVIEW_REQUIRED";
  const userSelected = row.selection_type === "USER_SELECTED" || row.match_type === "USER_SELECTED";

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
          <dd className="part">{displayedProductcode(row)}</dd>
        </div>
        <div>
          <dt>Matched Description</dt>
          <dd>{row.matched_description || "—"}</dd>
        </div>
        <div>
          <dt>Match Type</dt>
          <dd>
            {userSelected
              ? "User Selected"
              : row.match_type_label || (row.selection_type === "AUTOMATIC" ? "Automatic" : "—")}
          </dd>
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
          <dt>Overall confidence</dt>
          <dd>{overallPercent(row)}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={`status ${badge.toLowerCase()}`}>{statusLabel(row.match_status)}</span>
          </dd>
        </div>
      </dl>

      <MatchEvidencePanel row={row} />

      {row.match_reason ? (
        <div className="candidate-reason">
          <h3>Explanation</h3>
          <p>{row.match_reason}</p>
        </div>
      ) : null}

      {review ? <p className="review-callout">REVIEW REQUIRED — select the correct product</p> : null}

      {badge === "NO_MATCH" ? (
        <p className="nomatch-callout">No matching Atkore part found</p>
      ) : null}

      {review && hasCandidates ? (
        <>
          <h3>Possible Matches</h3>
          <p className="hint">
            Input: {row.requested_description || row.requested_part_number}
          </p>
          <ul className="possible-matches">
            {row.candidates.slice(0, 3).map((candidate, index) => {
              const code = candidateProductcode(candidate);
              const rank = candidate.rank ?? index + 1;
              const confidence = Math.round(candidate.confidence ?? candidate.score);
              return (
                <li key={candidate.salsify_id || candidate.official_part_number || code}>
                  <div className="possible-match-rank">#{rank}</div>
                  <div className="possible-match-body">
                    <div className="part">
                      {code}
                      <CandidateAtkoreLink candidate={candidate} />
                    </div>
                    <div>{candidateName(candidate)}</div>
                    {candidate.description2 ? (
                      <div className="hint">{candidate.description2}</div>
                    ) : null}
                    <div className="hint">{candidateReason(candidate)}</div>
                  </div>
                  <div className="possible-match-actions">
                    <div className="candidate-score">{confidence}%</div>
                    <button
                      type="button"
                      className="btn-navy btn-select"
                      disabled={selecting || !onSelectCandidate || code === "—"}
                      onClick={() => onSelectCandidate?.(row, code)}
                    >
                      Select
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      ) : hasCandidates ? (
        <>
          <h3>Top Candidates</h3>
          <ul className="candidates">
            {row.candidates.map((candidate) => (
              <li key={candidate.salsify_id || candidate.official_part_number}>
                <div>
                  <div className="part">
                    {candidateProductcode(candidate)}
                    <CandidateAtkoreLink candidate={candidate} />
                  </div>
                  {candidateName(candidate) && candidateName(candidate) !== candidateProductcode(candidate) ? (
                    <div>{candidateName(candidate)}</div>
                  ) : null}
                  {candidate.match_reasons.length > 0 ? (
                    <div className="hint">{candidate.match_reasons.join("; ")}</div>
                  ) : null}
                </div>
                <div className="candidate-score">{Math.round(candidate.confidence ?? candidate.score)}%</div>
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
