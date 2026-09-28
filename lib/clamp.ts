/**
 * Ограничивает value диапазоном [min, max].
 * Бросает RangeError, если min > max или любой из аргументов NaN.
 */
export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value) || Number.isNaN(min) || Number.isNaN(max)) {
    throw new RangeError(
      `clamp: arguments must not be NaN, got value=${value}, min=${min}, max=${max}`,
    );
  }

  if (min > max) {
    throw new RangeError(`clamp: min must be <= max, got min=${min}, max=${max}`);
  }

  if (value < min) return min;
  if (value > max) return max;
  return value;
}
