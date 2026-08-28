export type MatchStatus =
  | "CONFIDENT_MATCH"
  | "EXACT_MATCH"
  | "HIGH_CONFIDENCE"
  | "REVIEW_REQUIRED"
  | "NO_MATCH";

export type ConfidenceLabel = "HIGH" | "MEDIUM" | "LOW" | "REVIEW";

export interface FieldEvidence {
  field: string;
  level: "exact" | "strong" | "partial" | "none";
  label: string;
  score: number;
}

export interface MatchEvidence {
  status_label: "MATCH" | "REVIEW_REQUIRED" | "NO_MATCH" | string;
  matched_part_number: string | null;
  overall_percent: number;
  headline: string;
  fields: FieldEvidence[];
  detail_reasons?: string[];
  matching_tokens?: string[];
  normalized_terms?: string[];
  voltage_evidence?: string[];
  numeric_units?: string;
  candidate_separation?: string;
  productcode_match_type?: string;
}

export interface CandidateMatchEvidence {
  productcode_match_type?: string;
  headline?: string;
  fields?: FieldEvidence[];
  detail_reasons?: string[];
}

export interface CandidateProduct {
  rank?: number | null;
  productcode?: string | null;
  official_part_number: string;
  name?: string | null;
  description: string | null;
  description2?: string | null;
  salsify_id: string | null;
  confidence?: number;
  score: number;
  match_status?: string;
  match_reason?: string;
  match_reasons: string[];
  field_scores?: Record<string, number>;
  match_evidence?: CandidateMatchEvidence;
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
  match_breakdown?: {
    productcode_score?: number;
    name_score?: number;
    description_score?: number;
    description2_score?: number;
    overall_score?: number;
    match_reason?: string;
  } | null;
  match_evidence?: MatchEvidence;
  quote_line_id?: string | null;
  selection_type?: "AUTOMATIC" | "USER_SELECTED" | string | null;
  match_type?: "AUTOMATIC" | "USER_SELECTED" | string | null;
  match_type_label?: string | null;
  original_confidence?: number | null;
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
