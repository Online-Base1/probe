import { describe, expect, it } from "vitest";

import { groupBy } from "../../lib/group-by";

describe("groupBy", () => {
  it("groups elements by the key returned by keyFn", () => {
    const items = [
      { type: "fruit", name: "apple" },
      { type: "veg", name: "carrot" },
      { type: "fruit", name: "banana" },
    ];

    expect(groupBy(items, (item) => item.type)).toEqual({
      fruit: [
        { type: "fruit", name: "apple" },
        { type: "fruit", name: "banana" },
      ],
      veg: [{ type: "veg", name: "carrot" }],
    });
  });

  it("preserves the original array order within each group", () => {
    const numbers = [1, 2, 3, 4, 5, 6];

    const result = groupBy(numbers, (n) => (n % 2 === 0 ? "even" : "odd"));

    expect(result.odd).toEqual([1, 3, 5]);
    expect(result.even).toEqual([2, 4, 6]);
  });

  it("returns an empty object for an empty array", () => {
    expect(groupBy([], (item: unknown) => item)).toEqual({});
  });

  it("does not mutate the original array", () => {
    const items = [1, 2, 3];
    const original = [...items];

    groupBy(items, (n) => n % 2);

    expect(items).toEqual(original);
  });
});
