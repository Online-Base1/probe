import { describe, expect, it } from "vitest";
import { pageCount } from "../../lib/page-count";

describe("pageCount", () => {
  it("возвращает число страниц с округлением вверх для неполной последней страницы", () => {
    expect(pageCount(11, 10)).toBe(2);
    expect(pageCount(20, 10)).toBe(2);
  });

  it("при total равном 0 возвращает 0", () => {
    expect(pageCount(0, 5)).toBe(0);
  });

  it("корректно считает на минимальных допустимых целых значениях total и pageSize", () => {
    expect(pageCount(1, 1)).toBe(1);
  });
});
