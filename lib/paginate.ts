/**
 * Число страниц для total элементов по pageSize на странице.
 * Последняя страница может быть неполной. Некорректные аргументы — RangeError.
 */
export function pageCount(total: number, pageSize: number): number {
  if (!Number.isInteger(total) || total < 0 || !Number.isInteger(pageSize) || pageSize < 1) {
    throw new RangeError(`pageCount: bad arguments total=${total}, pageSize=${pageSize}`);
  }
  return Math.floor(total / pageSize);
}
