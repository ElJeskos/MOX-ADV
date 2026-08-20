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

export function validateWeeklyBudgetRub(value: unknown, minimum: number) {
  const budget = Number(value);
  if (!Number.isFinite(budget) || budget <= 0) {
    throw new Error("Недельный бюджет должен быть положительным числом.");
  }
  if (budget < minimum) {
    throw new Error(`Недельный бюджет должен быть не меньше ${minimum} ₽ — это актуальный минимум Яндекс Директа для RUB.`);
  }
  return budget;
}
