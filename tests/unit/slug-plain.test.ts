import { describe, expect, it } from "vitest";
import { slugify } from "../../lib/slug-plain";

describe("slugify", () => {
  it("приводит результат к нижнему регистру", () => {
    expect(slugify("HeLLoWORLD123")).toBe("helloworld123");
  });

  it("заменяет каждую серию не-ASCII-латиницы-и-цифр одним дефисом", () => {
    expect(slugify("Hello___,,   world!!42")).toBe("hello-world-42");
  });

  it("убирает дефисы в начале и в конце", () => {
    expect(slugify("  ---Hello world---  ")).toBe("hello-world");
  });

  it("считает не-ASCII буквы разделителями (K и İ не попадают в результат)", () => {
    expect(slugify("xKyİz")).toBe("x-y-z");
  });

  it("возвращает пустую строку для пустого и пробельного входа", () => {
    expect(slugify("")).toBe("");
    expect(slugify(" \t\n  ")).toBe("");
  });
});
