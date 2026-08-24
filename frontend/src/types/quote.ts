export type MatchStatus =
  | "CONFIDENT_MATCH"
  | "EXACT_MATCH"
  | "HIGH_CONFIDENCE"
  | "REVIEW_REQUIRED"
  | "NO_MATCH";

export type ConfidenceLabel = "HIGH" | "MEDIUM" | "LOW" | "REVIEW";

export interface CandidateProduct {
  official_part_number: string;
  description: string | null;
  salsify_id: string | null;
  score: number;
  match_reasons: string[];
}

export interface QuoteMatchResult {
  source_row: number | null;
  requested_part_number?: string | null;
  requested_description: string;
  quantity: number | null;
  matched_part_number: string | null;
  matched_salsify_id?: string | null;
  matched_description: string | null;
  customer_raw_text?: string | null;
  detected_salsify_id?: string | null;
  detected_part_number?: string | null;
  matching_percentage: number;
  part_number_match_score?: number | null;
  description_match_score?: number | null;
  overall_match_score?: number | null;
  part_number_match?: boolean;
  description_match?: boolean;
  confidence: ConfidenceLabel;
  match_status: MatchStatus;
  match_reason: string;
  candidate_count: number;
  candidates: CandidateProduct[];
}

export interface QuoteSummary {
  total: number;
  matched: number;
  review_required: number;
  no_match: number;
}

export interface QuoteProcessResponse {
  summary: QuoteSummary;
  results: QuoteMatchResult[];
}
