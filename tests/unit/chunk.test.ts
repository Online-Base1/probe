import { describe, expect, it } from "vitest";

import { chunk } from "../../lib/chunk";

describe("chunk", () => {
  it("splits an array into subarrays of the given size, in order", () => {
    expect(chunk([1, 2, 3, 4], 2)).toEqual([
      [1, 2],
      [3, 4],
    ]);
  });

  it("makes the last chunk shorter when the length does not divide evenly", () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
  });

  it("returns an empty array for an empty input array", () => {
    expect(chunk([], 3)).toEqual([]);
  });

  it("throws an Error when size is zero", () => {
    expect(() => chunk([1, 2, 3], 0)).toThrow(Error);
  });

  it("throws an Error when size is negative", () => {
    expect(() => chunk([1, 2, 3], -1)).toThrow(Error);
  });

  it("does not mutate the original array", () => {
    const original = [1, 2, 3, 4, 5];
    const copy = [...original];
    chunk(original, 2);
    expect(original).toEqual(copy);
  });

  it("returns a single chunk when size is larger than the array length", () => {
    expect(chunk([1, 2], 5)).toEqual([[1, 2]]);
  });
});
