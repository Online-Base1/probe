/**
 * Группирует элементы массива по ключу, возвращаемому keyFn.
 * Порядок элементов внутри каждой группы совпадает с порядком в array.
 * Пустой массив → {}. Исходный массив не изменяется.
 */
export function groupBy<T, K extends PropertyKey>(
  array: readonly T[],
  keyFn: (item: T) => K,
): Record<K, T[]> {
  const result = {} as Record<K, T[]>;

  for (const item of array) {
    const key = keyFn(item);
    const group = result[key];
    if (group) {
      group.push(item);
    } else {
      result[key] = [item];
    }
  }

  return result;
}
