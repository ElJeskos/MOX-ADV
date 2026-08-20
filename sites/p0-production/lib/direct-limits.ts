type CurrencyProperty = { Name?: unknown; Value?: unknown };
type CurrencyRow = { Currency?: unknown; Properties?: CurrencyProperty[] };

export function minimumWeeklyBudgetRub(currencies: CurrencyRow[]) {
  const rub = currencies.find((row) => row.Currency === "RUB");
  const property = rub?.Properties?.find((item) => item.Name === "MinimumWeeklySpendLimit");
  const micros = Number(property?.Value);
  if (!Number.isFinite(micros) || micros <= 0) {
    throw new Error("Direct Currencies не вернул минимальный недельный бюджет для RUB.");
  }
  return micros / 1_000_000;
}

export function weeklyBudgetValidationMessage(value: unknown, minimum: number) {
  const entered = String(value ?? "").trim();
  if (!entered) return "";
  const budget = Number(entered);
  if (!Number.isFinite(budget) || budget <= 0) {
    return "Введите положительный недельный бюджет.";
  }
  if (budget < minimum) {
    return `Минимальный недельный бюджет в Яндекс Директе — ${minimum} ₽. Укажите ${minimum} ₽ или больше.`;
  }
  return "";
}

export function validateWeeklyBudgetRub(value: unknown, minimum: number) {
  const message = weeklyBudgetValidationMessage(value, minimum);
  if (message) throw new Error(message);
  const budget = Number(value);
  if (!Number.isFinite(budget) || budget <= 0) {
    throw new Error("Недельный бюджет должен быть положительным числом.");
  }
  return budget;
}
