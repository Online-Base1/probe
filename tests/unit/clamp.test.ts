import { describe, expect, it } from "vitest";

import { clamp } from "../../lib/clamp";

describe("clamp", () => {
  it("returns value unchanged when within range", () => {
    expect(clamp(5, 0, 10)).toBe(5);
  });

  it("returns min when value is below range", () => {
    expect(clamp(-5, 0, 10)).toBe(0);
  });

  it("returns max when value is above range", () => {
    expect(clamp(15, 0, 10)).toBe(10);
  });

  it("returns value when equal to min", () => {
    expect(clamp(0, 0, 10)).toBe(0);
  });

  it("returns value when equal to max", () => {
    expect(clamp(10, 0, 10)).toBe(10);
  });

  it("handles negative ranges", () => {
    expect(clamp(-15, -10, -5)).toBe(-10);
    expect(clamp(-1, -10, -5)).toBe(-5);
    expect(clamp(-7, -10, -5)).toBe(-7);
  });

  it("returns value when min equals max and value matches", () => {
    expect(clamp(5, 5, 5)).toBe(5);
  });

  it("clamps to the single point when min equals max", () => {
    expect(clamp(100, 5, 5)).toBe(5);
    expect(clamp(-100, 5, 5)).toBe(5);
  });

  it("throws RangeError when min > max", () => {
    expect(() => clamp(5, 10, 0)).toThrow(RangeError);
  });

  it("throws RangeError when value is NaN", () => {
    expect(() => clamp(NaN, 0, 10)).toThrow(RangeError);
  });

  it("throws RangeError when min is NaN", () => {
    expect(() => clamp(5, NaN, 10)).toThrow(RangeError);
  });

  it("throws RangeError when max is NaN", () => {
    expect(() => clamp(5, 0, NaN)).toThrow(RangeError);
  });

  it("handles Infinity as bounds", () => {
    expect(clamp(5, -Infinity, Infinity)).toBe(5);
    expect(clamp(-Infinity, 0, 10)).toBe(0);
    expect(clamp(Infinity, 0, 10)).toBe(10);
  });
});
