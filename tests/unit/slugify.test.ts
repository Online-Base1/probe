import { describe, expect, it } from "vitest";

import { slugify } from "../../lib/slugify";

describe("slugify", () => {
  it("lowercases and strips diacritics via NFD", () => {
    expect(slugify("café")).toBe("cafe");
  });

  it("handles multiple accented letters and spaces", () => {
    expect(slugify("Crème Brûlée")).toBe("creme-brulee");
  });

  it("collapses repeated separators and trailing punctuation", () => {
    expect(slugify("naïve  façade!")).toBe("naive-facade");
  });

  it("turns punctuation and spaces into a single hyphen", () => {
    expect(slugify("Hello, World")).toBe("hello-world");
  });

  it("returns an empty string for empty input", () => {
    expect(slugify("")).toBe("");
  });

  it("returns an empty string when input is only separators", () => {
    expect(slugify("---")).toBe("");
  });

  // ß, ø, ł и æ не имеют канонического разложения в NFD (это не буква
  // с диакритикой поверх базовой латинской, а отдельные кодовые точки),
  // поэтому normalize("NFD") их не трогает. Дальше они не проходят фильтр
  // [a-z0-9] и превращаются в дефис как любой другой недопустимый символ.
  // Открытый вопрос для владельца: если ожидается транслитерация
  // (ß -> ss, ø -> o, ł -> l, æ -> ae), это поведение нужно менять явной
  // таблицей замен, а не полагаться на NFD.
  it("does not transliterate letters without an NFD decomposition (documents actual behavior)", () => {
    expect(slugify("straße")).toBe("stra-e");
    expect(slugify("øre")).toBe("re");
    expect(slugify("łąka")).toBe("aka");
    expect(slugify("æther")).toBe("ther");
  });
});
