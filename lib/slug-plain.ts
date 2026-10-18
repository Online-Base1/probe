/**
 * Converts a string to a URL-friendly slug.
 *
 * Only ASCII letters (A-Z/a-z) and digits (0-9) are treated as content;
 * every other character — including non-ASCII letters such as the Kelvin
 * sign (U+212A) or Turkish İ (U+0130), whose locale-aware lower-casing
 * would otherwise leak ASCII letters into the output — is treated purely
 * as a separator and never appears in the result.
 */
export function slugify(input: string): string {
  let result = "";
  let atSeparator = true;

  for (const char of input) {
    if (/^[A-Za-z0-9]$/.test(char)) {
      result += char.toLowerCase();
      atSeparator = false;
    } else if (!atSeparator) {
      result += "-";
      atSeparator = true;
    }
  }

  return result.endsWith("-") ? result.slice(0, -1) : result;
}
