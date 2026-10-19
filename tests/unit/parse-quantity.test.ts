import { describe, expect, it } from "vitest";
import { parseQuantity } from "../../lib/parse-quantity";

describe("parseQuantity", () => {
  it("parses a digit-only string as a number", () => {
    expect(parseQuantity("12345")).toBe(12345);
  });

  it("parses a digit-only string with surrounding spaces", () => {
    expect(parseQuantity("  0042  ")).toBe(42);
  });

  it("returns null for empty or spaces-only strings", () => {
    expect(parseQuantity("")).toBeNull();
    expect(parseQuantity("     ")).toBeNull();
  });

  it("returns null for strings with letters, sign, dot, or comma", () => {
    expect(parseQuantity("12a")).toBeNull();
    expect(parseQuantity("+12")).toBeNull();
    expect(parseQuantity("-12")).toBeNull();
    expect(parseQuantity("12.5")).toBeNull();
    expect(parseQuantity("12,5")).toBeNull();
  });
});
