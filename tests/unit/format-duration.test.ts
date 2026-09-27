import { describe, expect, it } from "vitest";

import { formatDuration } from "../../lib/format-duration";

describe("formatDuration", () => {
  it("formats zero as '0 с'", () => {
    expect(formatDuration(0)).toBe("0 с");
  });

  it("formats seconds only, omitting minutes and hours", () => {
    expect(formatDuration(3000)).toBe("3 с");
  });

  it("formats minutes and seconds, omitting hours", () => {
    expect(formatDuration(63000)).toBe("1 мин 3 с");
  });

  it("formats hours, minutes and seconds", () => {
    expect(formatDuration(3723000)).toBe("1 ч 2 мин 3 с");
  });

  it("keeps zero minutes when hours are present", () => {
    expect(formatDuration(3600000)).toBe("1 ч 0 мин 0 с");
  });

  it("keeps zero seconds when minutes are present", () => {
    expect(formatDuration(120000)).toBe("2 мин 0 с");
  });

  it("floors sub-second remainders", () => {
    expect(formatDuration(1999)).toBe("1 с");
  });

  it("floors milliseconds below one second to zero", () => {
    expect(formatDuration(999)).toBe("0 с");
  });

  it("handles large durations spanning many hours", () => {
    expect(formatDuration(90000000)).toBe("25 ч 0 мин 0 с");
  });

  it("throws RangeError for negative values", () => {
    expect(() => formatDuration(-1)).toThrow(RangeError);
  });

  it("throws RangeError for negative fractional values", () => {
    expect(() => formatDuration(-0.5)).toThrow(RangeError);
  });

  it("throws RangeError for non-integer values", () => {
    expect(() => formatDuration(1500.5)).toThrow(RangeError);
  });

  it("throws RangeError for NaN", () => {
    expect(() => formatDuration(NaN)).toThrow(RangeError);
  });

  it("throws RangeError for Infinity", () => {
    expect(() => formatDuration(Infinity)).toThrow(RangeError);
  });

  it("accepts negative zero as zero", () => {
    expect(formatDuration(-0)).toBe("0 с");
  });
});
