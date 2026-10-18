/**
 * Разбивает array на подмассивы длиной size по порядку.
 * Последний подмассив короче, если длина array не делится на size нацело.
 * Бросает Error, если size <= 0. Не мутирует исходный массив.
 */
export function chunk<T>(array: readonly T[], size: number): T[][] {
  if (size <= 0) {
    throw new Error(`chunk: size must be > 0, got ${size}`);
  }

  const result: T[][] = [];
  for (let i = 0; i < array.length; i += size) {
    result.push(array.slice(i, i + size));
  }
  return result;
}
