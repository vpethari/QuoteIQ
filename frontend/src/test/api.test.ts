import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, processQuote } from "../services/api";

const sampleBody = {
  summary: { total: 3, matched: 0, review_required: 3, no_match: 0 },
  results: [
    {
      source_row: 2,
      requested_description: "120V LIGHTING WHIP W/PAULEX",
      quantity: 5,
      matched_part_number: null,
      matching_percentage: 100,
      part_number_match_score: null,
      description_match_score: 100,
      overall_match_score: 100,
      confidence: "REVIEW",
      match_status: "REVIEW_REQUIRED",
      match_reason: "Multiple Atkore products have equivalent descriptions.",
      candidate_count: 0,
      candidates: [],
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("processQuote API client", () => {
  it("treats HTTP 200 JSON from /api/quote/process/results as success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => sampleBody,
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["abc"], "inputfile.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const payload = await processQuote(file, false);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/quote/process/results");
    expect(init.method).toBe("POST");
    expect(payload.summary).toEqual(sampleBody.summary);
    expect(payload.results[0]?.requested_description).toBe("120V LIGHTING WHIP W/PAULEX");
    expect(payload.results[0]?.matched_part_number).toBeNull();
  });

  it("does not classify a 200 response as service unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => sampleBody,
      }),
    );
    const file = new File(["abc"], "inputfile.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await expect(processQuote(file, false)).resolves.toMatchObject({
      summary: { total: 3, review_required: 3 },
    });
  });

  it("maps a network failure to service unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const file = new File(["abc"], "inputfile.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await expect(processQuote(file, false)).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message: "The QuoteIQ service is unavailable. Confirm the backend is running and try again.",
    });
    await expect(processQuote(file, false)).rejects.toBeInstanceOf(ApiError);
  });
});
