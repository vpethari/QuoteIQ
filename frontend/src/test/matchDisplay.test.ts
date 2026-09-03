import { describe, expect, it } from "vitest";
import { atkoreUrlForName } from "../lib/matchDisplay";

describe("atkoreUrlForName", () => {
  it("collapses internal whitespace and strips surrounding whitespace before encoding", () => {
    // productmaster.name carries raw fixed-width padding for some rows
    // (confirmed live: e.g. "P6291     EG") that would otherwise turn into
    // a broken-looking link full of encoded spaces.
    expect(atkoreUrlForName("P6291     EG")).toBe("https://www.atkore.com/product/P6291%20EG");
    expect(atkoreUrlForName("  SC75RKON  ")).toBe("https://www.atkore.com/product/SC75RKON");
  });

  it("leaves an already-clean name untouched", () => {
    expect(atkoreUrlForName("SC75RKON")).toBe("https://www.atkore.com/product/SC75RKON");
  });

  it("returns null for a blank or whitespace-only name", () => {
    expect(atkoreUrlForName(null)).toBeNull();
    expect(atkoreUrlForName(undefined)).toBeNull();
    expect(atkoreUrlForName("   ")).toBeNull();
  });
});
