import { describe, expect, it } from "vitest";
import { lastN } from "../../lib/last-n";

describe("lastN", () => {
  it("возвращает последние n элементов в исходном порядке", () => {
    const source = [1, 2, 3, 4, 5];

    const result = lastN(source, 3);

    expect(result).toEqual([3, 4, 5]);
    expect(result).not.toBe(source);
  });

  it("если n больше длины массива, возвращает копию всего массива", () => {
    const source = [10, 20];

    const result = lastN(source, 5);

    expect(result).toEqual([10, 20]);
    expect(result).not.toBe(source);
  });

  it("не мутирует исходный массив", () => {
    const source = [7, 8, 9];

    lastN(source, 2);

    expect(source).toEqual([7, 8, 9]);
  });

  it("при n = 0 возвращает пустой массив", () => {
    const source = [1, 2, 3];

    expect(lastN(source, 0)).toEqual([]);
  });
});
