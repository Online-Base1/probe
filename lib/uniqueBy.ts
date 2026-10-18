/**
 * Возвращает новый массив, в котором для каждого значения keyFn(элемент)
 * остаётся только первое вхождение. Порядок — как в исходном массиве.
 * Исходный массив не мутируется.
 */
export function uniqueBy<T, K>(array: readonly T[], keyFn: (item: T) => K): T[] {
  const seen = new Set<K>();
  const result: T[] = [];

  for (const item of array) {
    const key = keyFn(item);
    if (!seen.has(key)) {
      seen.add(key);
      result.push(item);
    }
  }

  return result;
}
