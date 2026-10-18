import { describe, expect, it } from "vitest";
import { uniqueBy } from "../../lib/uniqueBy";

describe("uniqueBy", () => {
  it("оставляет только первый элемент для каждого ключа и возвращает новый массив", () => {
    const source = [1, 2, 1, 3, 2];

    const result = uniqueBy(source, (item: number) => item);

    expect(result).toEqual([1, 2, 3]);
    expect(result).not.toBe(source);
  });

  it("сохраняет порядок первых вхождений как в исходном массиве", () => {
    const source = ["b1", "a1", "b2", "c1", "a2"];

    const result = uniqueBy(source, (item: string) => item[0]);

    expect(result).toEqual(["b1", "a1", "c1"]);
  });

  it("возвращает пустой массив для пустого входного массива", () => {
    const source: number[] = [];

    const result = uniqueBy(source, (item: number) => item);

    expect(result).toEqual([]);
  });

  it("не мутирует исходный массив", () => {
    const source = [
      { id: 1, value: "first-1" },
      { id: 2, value: "first-2" },
      { id: 1, value: "second-1" }
    ];
    const snapshot = source.map((item) => ({ ...item }));

    uniqueBy(source, (item: { id: number; value: string }) => item.id);

    expect(source).toEqual(snapshot);
  });
});
