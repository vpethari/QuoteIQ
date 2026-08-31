import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { QuoteProcessResponse } from "../types/quote";

const processQuote = vi.fn();
const downloadResultsCsv = vi.fn();
const downloadCpqReadyCsv = vi.fn();
const downloadBlob = vi.fn();

const selectQuoteMatch = vi.fn();

vi.mock("../services/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  processQuote: (...args: unknown[]) => processQuote(...args),
  downloadResultsCsv: (...args: unknown[]) => downloadResultsCsv(...args),
  downloadCpqReadyCsv: (...args: unknown[]) => downloadCpqReadyCsv(...args),
  downloadBlob: (...args: unknown[]) => downloadBlob(...args),
  selectQuoteMatch: (...args: unknown[]) => selectQuoteMatch(...args),
}));

const sample: QuoteProcessResponse = {
  summary: { total: 3, matched: 1, review_required: 2, no_match: 0 },
  results: [
    {
      source_row: 2,
      requested_description: "120V LIGHTING WHIP W/PAULEX",
      quantity: 5,
      matched_part_number: null,
      matched_description: null,
      matching_percentage: 100,
      part_number_match_score: null,
      description_match_score: 100,
      overall_match_score: 100,
      confidence: "REVIEW",
      match_status: "REVIEW_REQUIRED",
      match_reason: "Multiple Atkore products have equivalent descriptions.",
      candidate_count: 3,
      quote_line_id: "quote.xlsx|Sheet1|2|120V LIGHTING WHIP W/PAULEX",
      candidates: [
        {
          official_part_number: "1LAP-W",
          description: "120V LTG WHIP W/PAULEX",
          salsify_id: "NA1-1LAP-W",
          score: 100,
          match_reasons: ["Exact match"],
        },
        {
          official_part_number: "1LBP-W",
          description: "120V LIGHTING WHIP W/PAULEX",
          salsify_id: "NA1-1LBP-W",
          score: 100,
          match_reasons: ["Exact match"],
        },
        {
          official_part_number: "1LCP-W",
          description: "120V LIGHTING WHIP W/PAULEX",
          salsify_id: "NA1-1LCP-W",
          score: 100,
          match_reasons: ["Exact match"],
        },
      ],
    },
  ],
};

describe("QuoteIQ app", () => {
  beforeEach(() => {
    processQuote.mockReset();
    downloadResultsCsv.mockReset();
    downloadCpqReadyCsv.mockReset();
    downloadBlob.mockReset();
    selectQuoteMatch.mockReset();
  });

  it("renders the dashboard upload area and empty state", () => {
    render(<App />);
    expect(screen.getAllByText("QuoteIQ").length).toBeGreaterThan(0);
    expect(screen.getByText("Product")).toBeInTheDocument();
    expect(screen.getByText("Resources")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Atkore" })).toBeInTheDocument();
    expect(screen.getByText("Upload a Quote")).toBeInTheDocument();
    expect(screen.getByText("Quote Summary")).toBeInTheDocument();
    expect(screen.getByText(/Making/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Process Quote →" })).toBeDisabled();
    expect(screen.getByText(/Upload your Excel or PDF documents/)).toBeInTheDocument();
  });

  it("rejects unsupported files", async () => {
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const bad = new File(["x"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [bad] } });
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to process quote");
    expect(screen.getByRole("alert")).toHaveTextContent("Only .xlsx Excel or .pdf files are supported.");
    expect(screen.getByRole("button", { name: "Process Quote →" })).toBeDisabled();
  });

  it("selects an xlsx file and enables process", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["abc"], "inputfile.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    Object.defineProperty(file, "size", { value: 2048 });
    await user.upload(input, file);
    expect(screen.getByText("inputfile.xlsx")).toBeInTheDocument();
    expect(screen.getByText(/2\.0 KB/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Process Quote →" })).toBeEnabled();
  });

  it("selects a pdf file and enables process", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF-1.4"], "sample-quote.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: 4096 });
    await user.upload(input, file);
    expect(screen.getByText("sample-quote.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Process Quote →" })).toBeEnabled();
  });

  it("shows loading, KPIs, review details, download, and API errors", async () => {
    const user = userEvent.setup();
    let resolveProcess: (value: QuoteProcessResponse) => void = () => undefined;
    processQuote.mockImplementation(
      () =>
        new Promise<QuoteProcessResponse>((resolve) => {
          resolveProcess = resolve;
        }),
    );
    downloadResultsCsv.mockResolvedValue(new Blob(["csv"]));

    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      input,
      new File(["abc"], "inputfile.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    expect(screen.getByRole("button", { name: "Processing Quote..." })).toBeDisabled();
    expect(screen.getByText("Uploading...")).toBeInTheDocument();
    expect(screen.getByText("Analyzing Matches...")).toBeInTheDocument();
    resolveProcess(sample);
    expect(await screen.findByText("120V LIGHTING WHIP W/PAULEX")).toBeInTheDocument();
    expect(screen.getByText("Total Lines")).toBeInTheDocument();
    expect(screen.getByText("Match Rate")).toBeInTheDocument();
    expect(screen.getByText("33%")).toBeInTheDocument();
    expect(screen.getByText(/3 line items detected/)).toBeInTheDocument();
    expect(screen.getByText("Matched Part Number")).toBeInTheDocument();
    expect(screen.queryByText("Matched Atkore Part Number")).not.toBeInTheDocument();
    expect(screen.queryByText("Matched Salsify ID")).not.toBeInTheDocument();
    expect(screen.getByText("Confidence")).toBeInTheDocument();
    expect(screen.getByText("Why")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("REVIEW REQUIRED — 3 possible products")).toBeInTheDocument();
    expect(screen.getByText("No part selected")).toBeInTheDocument();
    expect(screen.getByText("Multiple products have equivalent description matches")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Review Match" }));
    expect(screen.getByText("Match Details")).toBeInTheDocument();
    expect(screen.getByText("Match Evidence")).toBeInTheDocument();
    expect(screen.getByText("Possible Matches")).toBeInTheDocument();
    expect(screen.getByText("1LAP-W")).toBeInTheDocument();
    expect(screen.getByText("1LBP-W")).toBeInTheDocument();
    expect(screen.getByText("1LCP-W")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Full Results" }));
    expect(downloadResultsCsv).toHaveBeenCalled();
    expect(downloadBlob).toHaveBeenCalled();

    const { ApiError } = await import("../services/api");
    processQuote.mockRejectedValueOnce(
      new ApiError("The QuoteIQ service is unavailable. Confirm the backend is running and try again.", 0),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("QuoteIQ service unavailable");
    expect(screen.getByRole("alert")).toHaveTextContent("Confirm the backend is running");
  });

  it("shows matched part numbers and candidate details without fabricating SKUs", async () => {
    const user = userEvent.setup();
    processQuote.mockResolvedValue({
      summary: { total: 1, matched: 1, review_required: 0, no_match: 0 },
      results: [
        {
          source_row: 2,
          requested_description: "120V DBL HEAD EXT CABLE",
          quantity: 5,
          matched_part_number: "1EEC",
          matched_salsify_id: "NA1-1EEC",
          matched_description: "120V DBL HEAD EXT CABLE",
          matching_percentage: 86,
          part_number_match_score: null,
          description_match_score: 86,
          overall_match_score: 86,
          confidence: "HIGH",
          match_status: "HIGH_CONFIDENCE",
          match_reason: "Top candidate is above the high-confidence threshold",
          candidate_count: 2,
          candidates: [
            {
              official_part_number: "1EEC",
              description: "120V DBL HEAD EXT CABLE",
              salsify_id: "NA1-1EEC",
              score: 86,
              match_reasons: ["Shared tokens: 120V, DBL, HEAD, EXT, CABLE"],
              name: "120V-DBL-HEAD-EXT-CABLE",
            },
            {
              official_part_number: "1EAG/A",
              description: "120V DBL HEAD EXT CABLE W/MOLEX",
              salsify_id: "NA1-1EAG/A",
              score: 72,
              match_reasons: ["Shared tokens: 120V, DBL, HEAD"],
            },
          ],
        },
      ],
    });
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      input,
      new File(["abc"], "inputfile.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    expect(await screen.findByText("1EEC")).toBeInTheDocument();
    expect(screen.getByText("MATCH")).toBeInTheDocument();
    expect(screen.getAllByText("86%").length).toBeGreaterThan(0);
    const atkoreLink = screen.getByRole("link", { name: "View on atkore.com" });
    expect(atkoreLink).toHaveAttribute("href", "https://www.atkore.com/products/120V-DBL-HEAD-EXT-CABLE");
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    await user.click(atkoreLink);
    expect(openSpy).toHaveBeenCalledWith(
      "https://www.atkore.com/products/120V-DBL-HEAD-EXT-CABLE",
      "atkoreProduct",
      expect.stringContaining("width="),
    );
    openSpy.mockRestore();
    await user.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByText("Match Details")).toBeInTheDocument();
    expect(screen.getByText("Match Evidence")).toBeInTheDocument();
    expect(screen.getByText("1EAG/A")).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
  });

  it("renders Productcode match evidence without using a database id", async () => {
    const user = userEvent.setup();
    processQuote.mockResolvedValue({
      summary: { total: 1, matched: 1, review_required: 0, no_match: 0 },
      results: [
        {
          source_row: 2,
          requested_description: "B1EB5-W BRP 120V WHIP END EXT CBL",
          quantity: 1,
          matched_part_number: "B1EB5-W",
          matched_salsify_id: "B1EB5-W",
          matched_description: "BRP 120V WHIP END EXT CBL",
          matching_percentage: 98,
          part_number_match_score: 100,
          description_match_score: 100,
          overall_match_score: 98,
          part_number_match: true,
          description_match: true,
          confidence: "HIGH",
          match_status: "EXACT_MATCH",
          match_reason: "Exact Productcode match",
          match_evidence: {
            status_label: "MATCH",
            matched_part_number: "B1EB5-W",
            overall_percent: 98,
            headline: "Exact Productcode + Description Match",
            fields: [
              { field: "Productcode", level: "exact", label: "Exact match", score: 100 },
              { field: "name", level: "none", label: "No match", score: 0 },
              { field: "description", level: "strong", label: "Strong match", score: 94 },
              { field: "description2", level: "none", label: "No match", score: 0 },
            ],
          },
          candidate_count: 1,
          candidates: [
            {
              official_part_number: "B1EB5-W",
              description: "BRP 120V WHIP END EXT CBL",
              salsify_id: "B1EB5-W",
              score: 98,
              match_reasons: ["Exact Productcode match"],
            },
          ],
        },
      ],
    });
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      input,
      new File(["abc"], "quote.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    expect(await screen.findByText("B1EB5-W")).toBeInTheDocument();
    expect(screen.queryByText("333427")).not.toBeInTheDocument();
    expect(screen.getByText("Exact Productcode + Description Match")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByText("Productcode — Exact match")).toBeInTheDocument();
    expect(screen.getByText("description — Strong match")).toBeInTheDocument();
    expect(screen.getByText("name — No match")).toBeInTheDocument();
    expect(screen.getByText("description2 — No match")).toBeInTheDocument();
  });

  it("displays numeric Productcode without thousands separators", async () => {
      const user = userEvent.setup();
      processQuote.mockResolvedValue({
        summary: { total: 1, matched: 1, review_required: 0, no_match: 0 },
        results: [
          {
            source_row: 2,
            requested_description: "333572",
            quantity: 1,
            matched_part_number: "333572",
            matched_salsify_id: "333572",
            matched_description: "G1MD04MMDD08092",
            matching_percentage: 100,
            part_number_match_score: 100,
            description_match_score: null,
            overall_match_score: 100,
            part_number_match: true,
            description_match: false,
            confidence: "HIGH",
            match_status: "EXACT_MATCH",
            match_reason: "Exact Productcode match",
            match_evidence: {
              status_label: "MATCH",
              matched_part_number: "333572",
              overall_percent: 100,
              headline: "Exact Productcode Match",
              fields: [
                { field: "Productcode", level: "exact", label: "Exact match", score: 100 },
                { field: "name", level: "none", label: "No match", score: 0 },
                { field: "description", level: "none", label: "No match", score: 0 },
                { field: "description2", level: "none", label: "No match", score: 0 },
              ],
            },
            candidate_count: 1,
            candidates: [
              {
                official_part_number: "333572",
                description: "G1MD04MMDD08092",
                salsify_id: "333572",
                score: 100,
                match_reasons: ["Exact Productcode match"],
              },
            ],
          },
        ],
      });
      render(<App />);
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      await user.upload(
        input,
        new File(["abc"], "quote.xlsx", {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }),
      );
      await user.click(screen.getByRole("button", { name: "Process Quote →" }));
      expect(await screen.findAllByText("333572")).not.toHaveLength(0);
      expect(screen.queryByText("333,572")).not.toBeInTheDocument();
    });

  it("renders no-match copy without inventing candidates", async () => {
    const user = userEvent.setup();
    processQuote.mockResolvedValue({
      summary: { total: 1, matched: 0, review_required: 0, no_match: 1 },
      results: [
        {
          source_row: 4,
          requested_description: "UNKNOWN WIDGET",
          quantity: 1,
          matched_part_number: null,
          matched_description: null,
          matching_percentage: 12,
          confidence: "LOW",
          match_status: "NO_MATCH",
          match_reason: "",
          candidate_count: 0,
          candidates: [],
        },
      ],
    });
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      input,
      new File(["abc"], "quote.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    expect(await screen.findByText("UNKNOWN WIDGET")).toBeInTheDocument();
    expect(screen.getByText("NO_MATCH")).toBeInTheDocument();
    expect(screen.getAllByText("0%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No matching Atkore part found").length).toBeGreaterThan(0);
    expect(screen.getByText("No part selected")).toBeInTheDocument();
    expect(screen.getByText("No sufficiently similar product found")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByText("Match Evidence")).toBeInTheDocument();
    expect(screen.getByText("No catalog candidates were returned for this line.")).toBeInTheDocument();
  });

  it("lets a reviewer select a possible match", async () => {
    const user = userEvent.setup();
    processQuote.mockResolvedValue(sample);
    selectQuoteMatch.mockResolvedValue({
      ...sample.results[0],
      matched_part_number: "1LBP-W",
      matched_description: "120V LIGHTING WHIP W/PAULEX",
      match_status: "HIGH_CONFIDENCE",
      selection_type: "USER_SELECTED",
      match_type: "USER_SELECTED",
      match_type_label: "User Selected",
      original_confidence: 100,
      overall_match_score: 100,
      match_evidence: {
        status_label: "MATCH",
        matched_part_number: "1LBP-W",
        overall_percent: 100,
        headline: "User Selected Match",
        fields: [],
      },
    });
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      input,
      new File(["abc"], "inputfile.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    await user.click(await screen.findByRole("button", { name: "Review Match" }));
    const selectButtons = screen.getAllByRole("button", { name: "Select" });
    await user.click(selectButtons[1]);
    expect(selectQuoteMatch).toHaveBeenCalledWith(
      expect.objectContaining({
        productcode: "1LBP-W",
        quote_line_id: "quote.xlsx|Sheet1|2|120V LIGHTING WHIP W/PAULEX",
      }),
    );
    expect(await screen.findAllByText("User Selected")).not.toHaveLength(0);
    expect(screen.getAllByText("MATCH").length).toBeGreaterThan(0);
    expect(screen.getByText("1LBP-W")).toBeInTheDocument();
  });

  it("shows parse warnings from an unpredictable input file and lets a reviewer dismiss them", async () => {
    const user = userEvent.setup();
    processQuote.mockResolvedValue({
      ...sample,
      parse_warnings: [
        'No header row was found in "inputfile.xlsx" -- Description and Quantity columns were inferred from the data.',
      ],
    });
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      input,
      new File(["abc"], "inputfile.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    expect(await screen.findByText(/No header row was found/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/No header row was found/)).not.toBeInTheDocument();
  });

  it("downloads a CPQ-ready CSV via the CPQ Ready Items button", async () => {
    const user = userEvent.setup();
    processQuote.mockResolvedValue(sample);
    downloadCpqReadyCsv.mockResolvedValue(new Blob(["Productcode,Qty"]));
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      input,
      new File(["abc"], "inputfile.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    await screen.findByText("120V LIGHTING WHIP W/PAULEX");
    await user.click(screen.getByRole("button", { name: "CPQ Ready Items" }));
    expect(downloadCpqReadyCsv).toHaveBeenCalled();
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "QuoteIQ_CPQ_Ready.csv");
  });

  it("renders no parse-warnings banner when the response has none", async () => {
    const user = userEvent.setup();
    processQuote.mockResolvedValue(sample);
    render(<App />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      input,
      new File(["abc"], "inputfile.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Process Quote →" }));
    await screen.findByText("Quote Results");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
