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

const DURATION_UNIT_MS: Record<string, number> = {
  ч: 3600000,
  мин: 60000,
  с: 1000,
};

const DURATION_UNIT_ORDER = ["ч", "мин", "с"];

/**
 * Разбирает строку вида "1 ч 2 мин 3 с" в миллисекунды. Обратна formatDuration.
 * Допускает любое непустое подмножество частей ч/мин/с, но только в этом
 * порядке и без повторов. Некорректный ввод — RangeError.
 */
export function parseDuration(text: string): number {
  const trimmed = text.trim();
  const tokens = trimmed.length > 0 ? trimmed.split(/\s+/) : [];

  if (tokens.length === 0 || tokens.length % 2 !== 0) {
    throw new RangeError(`parseDuration: invalid duration string, got ${JSON.stringify(text)}`);
  }

  let ms = 0;
  let lastUnitIndex = -1;

  for (let i = 0; i < tokens.length; i += 2) {
    const numberToken = tokens[i];
    const unitToken = tokens[i + 1];

    if (!/^\d+$/.test(numberToken)) {
      throw new RangeError(`parseDuration: invalid duration string, got ${JSON.stringify(text)}`);
    }

    const unitIndex = DURATION_UNIT_ORDER.indexOf(unitToken);
    if (unitIndex === -1 || unitIndex <= lastUnitIndex) {
      throw new RangeError(`parseDuration: invalid duration string, got ${JSON.stringify(text)}`);
    }
    lastUnitIndex = unitIndex;

    ms += Number(numberToken) * DURATION_UNIT_MS[unitToken];
  }

  return ms;
}
