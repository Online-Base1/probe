import { describe, expect, it } from "vitest";

import { pageCount } from "../../lib/paginate";

describe("pageCount", () => {
  it("returns 0 for no items", () => {
    expect(pageCount(0, 10)).toBe(0);
  });

  it("returns 1 for exactly one full page", () => {
    expect(pageCount(10, 10)).toBe(1);
  });

  it("counts several full pages", () => {
    expect(pageCount(20, 10)).toBe(2);
    expect(pageCount(100, 25)).toBe(4);
  });

  it("throws on invalid arguments", () => {
    expect(() => pageCount(-1, 10)).toThrow(RangeError);
    expect(() => pageCount(10, 0)).toThrow(RangeError);
    expect(() => pageCount(1.5, 10)).toThrow(RangeError);
    expect(() => pageCount(10, 2.5)).toThrow(RangeError);
  });
});
