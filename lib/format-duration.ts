/**
 * Форматирует длительность в миллисекундах как строку вида "1 ч 2 мин 3 с".
 * Нулевые старшие части опускаются: "2 мин 3 с", "3 с". 0 → "0 с".
 * Дробная часть менее секунды отбрасывается (округление вниз).
 */
export function formatDuration(ms: number): string {
  if (!Number.isInteger(ms) || ms < 0) {
    throw new RangeError(
      `formatDuration: ms must be a non-negative integer, got ${ms}`,
    );
  }

  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours} ч`);
  if (hours > 0 || minutes > 0) parts.push(`${minutes} мин`);
  parts.push(`${seconds} с`);

  return parts.join(" ");
}
