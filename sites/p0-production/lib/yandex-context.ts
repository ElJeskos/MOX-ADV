type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

type DirectBindingConfig = {
  token: string;
  expectedAccount: string;
};

type MetrikaBindingConfig = {
  token: string;
  expectedCounterId: string;
  expectedGoalId: string;
};

export class YandexContextError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "YandexContextError";
    this.code = code;
  }
}

function fail(code: string, message: string): never {
  throw new YandexContextError(code, message);
}

function required(value: string, code: string, message: string) {
  const result = value.trim();
  if (!result) fail(code, message);
  return result;
}

async function officialJson(response: Response, provider: "Direct" | "Metrika") {
  if (!response.ok) {
    fail(`${provider.toUpperCase()}_API_UNAVAILABLE`, `${provider} API вернул HTTP ${response.status}.`);
  }
  try {
    return await response.json() as Record<string, unknown>;
  } catch {
    fail(`${provider.toUpperCase()}_API_INVALID`, `${provider} API вернул некорректный JSON.`);
  }
}

export async function verifyDirectAccountBinding(
  config: DirectBindingConfig,
  fetchImpl: FetchLike,
  now: () => string,
) {
  const token = required(config.token, "DIRECT_AUTHORITY_MISSING", "Direct read authority не настроена.");
  const expectedAccount = required(
    config.expectedAccount,
    "DIRECT_ACCOUNT_BINDING_MISSING",
    "Direct advertiser account не настроен.",
  );
  let response: Response;
  try {
    response = await fetchImpl("https://api.direct.yandex.com/json/v501/clients", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Client-Login": expectedAccount,
        Accept: "application/json",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
      },
      body: JSON.stringify({
        method: "get",
        params: {
          SelectionCriteria: { Logins: [expectedAccount] },
          FieldNames: ["Login", "ClientId"],
        },
      }),
    });
  } catch {
    fail("DIRECT_API_UNAVAILABLE", "Direct API недоступен для проверки advertiser binding.");
  }
  const payload = await officialJson(response, "Direct") as {
    error?: unknown;
    result?: { Clients?: Array<{ Login?: unknown; ClientId?: unknown }> };
  };
  if (payload.error || !Array.isArray(payload.result?.Clients)) {
    fail("DIRECT_API_INVALID", "Direct clients.get не подтвердил advertiser binding.");
  }
  const matching = payload.result.Clients.filter((item) => String(item.Login ?? "") === expectedAccount);
  if (matching.length !== 1) {
    fail("DIRECT_ACCOUNT_BINDING_MISMATCH", "Direct API не подтвердил точный advertiser account binding.");
  }
  return {
    authority: "VERIFIED" as const,
    access: "YANDEX_DIRECT_API_V501" as const,
    account: expectedAccount,
    client_id: String(matching[0].ClientId ?? ""),
    binding: {
      expected_account: expectedAccount,
      api_account: String(matching[0].Login),
      matched: true as const,
    },
    observed_at: now(),
  };
}

export async function verifyMetrikaCounterBinding(
  config: MetrikaBindingConfig,
  fetchImpl: FetchLike,
  now: () => string,
) {
  const token = required(config.token, "METRIKA_AUTHORITY_MISSING", "Metrika read authority не настроена.");
  const expectedCounterId = required(
    config.expectedCounterId,
    "METRIKA_COUNTER_BINDING_MISSING",
    "Metrika counter binding не настроен.",
  );
  const expectedGoalId = required(
    config.expectedGoalId,
    "METRIKA_GOAL_BINDING_MISSING",
    "Metrika goal binding не настроен.",
  );
  const headers = { Authorization: `OAuth ${token}`, Accept: "application/json" };
  let counterResponse: Response;
  try {
    counterResponse = await fetchImpl(
      `https://api-metrika.yandex.net/management/v1/counter/${encodeURIComponent(expectedCounterId)}`,
      { headers },
    );
  } catch {
    fail("METRIKA_API_UNAVAILABLE", "Metrika API недоступен для проверки counter binding.");
  }
  const counterPayload = await officialJson(counterResponse, "Metrika") as {
    counter?: { id?: unknown };
  };
  const apiCounterId = String(counterPayload.counter?.id ?? "");
  if (apiCounterId !== expectedCounterId) {
    fail("METRIKA_COUNTER_BINDING_MISMATCH", "Metrika API не подтвердил точный counter binding.");
  }
  let goalsResponse: Response;
  try {
    goalsResponse = await fetchImpl(
      `https://api-metrika.yandex.net/management/v1/counter/${encodeURIComponent(expectedCounterId)}/goals`,
      { headers },
    );
  } catch {
    fail("METRIKA_API_UNAVAILABLE", "Metrika API недоступен для проверки goal binding.");
  }
  const goalsPayload = await officialJson(goalsResponse, "Metrika") as {
    goals?: Array<{ id?: unknown }>;
  };
  if (!Array.isArray(goalsPayload.goals)) {
    fail("METRIKA_API_INVALID", "Metrika goals API не подтвердил goal binding.");
  }
  const matching = goalsPayload.goals.filter((item) => String(item.id ?? "") === expectedGoalId);
  if (matching.length !== 1) {
    fail("METRIKA_GOAL_BINDING_MISMATCH", "Metrika API не подтвердил точный goal binding.");
  }
  return {
    authority: "VERIFIED" as const,
    access: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API" as const,
    counter_id: expectedCounterId,
    goal_id: expectedGoalId,
    binding: {
      expected_counter_id: expectedCounterId,
      api_counter_id: apiCounterId,
      matched: true as const,
    },
    goal_binding: {
      expected_goal_id: expectedGoalId,
      api_goal_id: String(matching[0].id),
      matched: true as const,
    },
    observed_at: now(),
  };
}
