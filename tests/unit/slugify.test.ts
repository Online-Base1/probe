import { describe, expect, it } from "vitest";

import { slugify } from "../../lib/slugify";

describe("slugify", () => {
  it("returns an empty string for an empty input", () => {
    expect(slugify("")).toBe("");
  });

  it("returns an empty string when input is only spaces", () => {
    expect(slugify("   ")).toBe("");
  });

  it("returns an empty string when input has only punctuation", () => {
    expect(slugify("!!!???")).toBe("");
  });

  it("lowercases latin letters and keeps digits", () => {
    expect(slugify("Hello World 123")).toBe("hello-world-123");
  });

  it("collapses multiple separators into one hyphen", () => {
    expect(slugify("a   b---c")).toBe("a-b-c");
  });

  it("strips leading and trailing hyphens after replacement", () => {
    expect(slugify("  --Hello--  ")).toBe("hello");
  });

  it("leaves an already valid slug unchanged", () => {
    expect(slugify("already-a-slug-42")).toBe("already-a-slug-42");
  });

  it("transliterates lowercase cyrillic letters", () => {
    expect(slugify("привет мир")).toBe("privet-mir");
  });

  it("transliterates uppercase cyrillic letters", () => {
    expect(slugify("ПРИВЕТ МИР")).toBe("privet-mir");
  });

  it("transliterates the full cyrillic alphabet", () => {
    expect(slugify("абвгдежзийклмнопрстуфхцчшщъыьэюя")).toBe(
      "abvgdezhziyklmnoprstufhtschshshchyeyuya",
    );
  });

  it("drops the hard sign without leaving a stray hyphen", () => {
    expect(slugify("объём")).toBe("obem");
  });

  it("replaces other unicode punctuation and symbols with a hyphen", () => {
    expect(slugify("hello — world © 2024")).toBe("hello-world-2024");
  });

  it("keeps a single-character result intact", () => {
    expect(slugify("a")).toBe("a");
  });

  it("transliterates a single cyrillic character", () => {
    expect(slugify("я")).toBe("ya");
  });
});
