import { describe, expect, it } from "vitest";

import { formatDuration, parseDuration } from "../../lib/format-duration";

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

describe("parseDuration", () => {
  it("parses hours, minutes and seconds", () => {
    expect(parseDuration("1 ч 2 мин 3 с")).toBe(3723000);
  });

  it("parses minutes and seconds only", () => {
    expect(parseDuration("2 мин 3 с")).toBe(123000);
  });

  it("parses seconds only", () => {
    expect(parseDuration("3 с")).toBe(3000);
  });

  it("parses minutes only", () => {
    expect(parseDuration("2 мин")).toBe(120000);
  });

  it("parses hours only", () => {
    expect(parseDuration("1 ч")).toBe(3600000);
  });

  it("parses zero seconds", () => {
    expect(parseDuration("0 с")).toBe(0);
  });

  it("parses hours and seconds, skipping minutes", () => {
    expect(parseDuration("1 ч 3 с")).toBe(3603000);
  });

  it("parses large durations spanning many hours", () => {
    expect(parseDuration("25 ч 0 мин 0 с")).toBe(90000000);
  });

  it("collapses repeated whitespace and trims ends", () => {
    expect(parseDuration("  1 ч   2 мин  3 с  ")).toBe(3723000);
  });

  it("throws RangeError for an empty string", () => {
    expect(() => parseDuration("")).toThrow(RangeError);
  });

  it("throws RangeError for a blank string", () => {
    expect(() => parseDuration("   ")).toThrow(RangeError);
  });

  it("throws RangeError for an unknown unit", () => {
    expect(() => parseDuration("1 день")).toThrow(RangeError);
  });

  it("throws RangeError for a non-numeric amount", () => {
    expect(() => parseDuration("x с")).toThrow(RangeError);
  });

  it("throws RangeError for a negative amount", () => {
    expect(() => parseDuration("-1 с")).toThrow(RangeError);
  });

  it("throws RangeError for a fractional amount", () => {
    expect(() => parseDuration("1.5 с")).toThrow(RangeError);
  });

  it("throws RangeError for units out of order", () => {
    expect(() => parseDuration("3 с 2 мин")).toThrow(RangeError);
  });

  it("throws RangeError for a repeated unit", () => {
    expect(() => parseDuration("1 ч 2 ч")).toThrow(RangeError);
  });

  it("throws RangeError for trailing garbage", () => {
    expect(() => parseDuration("1 ч 2 мин 3 с extra")).toThrow(RangeError);
  });

  it("throws RangeError for a dangling unit without a number", () => {
    expect(() => parseDuration("с")).toThrow(RangeError);
  });

  it("round-trips through formatDuration for whole seconds", () => {
    for (let seconds = 0; seconds <= 3660; seconds += 1) {
      const ms = seconds * 1000;
      expect(parseDuration(formatDuration(ms))).toBe(ms);
    }

    const largeSeconds = [7200, 36000, 90000, 359999, 360000];
    for (const seconds of largeSeconds) {
      const ms = seconds * 1000;
      expect(parseDuration(formatDuration(ms))).toBe(ms);
    }
  });
});
