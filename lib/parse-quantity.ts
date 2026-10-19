/**
 * Разбирает количество товара из текстового поля формы.
 * Допускается только строка из десятичных цифр (пробелы по краям игнорируются).
 * Любой другой формат (буквы, знак, точка, запятая, пустая строка) → null.
 */
export function parseQuantity(input: string): number | null {
  const trimmed = input.trim();
  if (!/^[0-9]+$/.test(trimmed)) {
    return null;
  }
  return Number(trimmed);
}
