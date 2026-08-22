export const P0_E2E_FIXTURE_SCENARIO = "mixed-correction";

export function localP0E2EFixtureScenario(
  requestUrl: string,
  configuredScenario: string | undefined,
) {
  const scenario = configuredScenario?.trim();
  if (scenario !== P0_E2E_FIXTURE_SCENARIO) return null;
  const hostname = new URL(requestUrl).hostname;
  return hostname === "localhost" || hostname === "127.0.0.1"
    ? scenario
    : null;
}
