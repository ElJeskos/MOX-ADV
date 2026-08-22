import { env } from "cloudflare:workers";
import { localP0E2EFixtureScenario } from "../../../lib/p0-e2e-boundary";
import { P0ApplicationError } from "../../../lib/p0-application";
import {
  applyAction as productionApplyAction,
  overview as productionOverview,
  userKey,
} from "../../../lib/p0";

function failure(error: unknown) {
  return {
    error: error instanceof Error ? error.message : "Production-модуль завершил действие fail closed.",
    ...(error instanceof P0ApplicationError ? { code: error.code } : {}),
  };
}

function localFixtureScenario(request: Request) {
  return localP0E2EFixtureScenario(
    request.url,
    (env as unknown as { P0_E2E_FIXTURE_SCENARIO?: string })
      .P0_E2E_FIXTURE_SCENARIO,
  );
}

async function fixtureBackend(request: Request) {
  const scenario = localFixtureScenario(request);
  if (!scenario) return null;
  const fixture = await import("../../../lib/p0-e2e-runtime");
  const key = userKey(request);
  return {
    overview: () => fixture.fixtureOverview(scenario, key),
    applyAction: (payload: Record<string, unknown>) => fixture.fixtureApplyAction(scenario, key, payload),
  };
}

export async function GET(request: Request) {
  try {
    const fixture = await fixtureBackend(request);
    const value = fixture
      ? await fixture.overview()
      : await productionOverview(userKey(request));
    return Response.json(value);
  } catch (error) {
    return Response.json(failure(error), { status: 503 });
  }
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as Record<string, unknown>;
    const fixture = await fixtureBackend(request);
    const value = fixture
      ? await fixture.applyAction(payload)
      : await productionApplyAction(userKey(request), payload);
    return Response.json(value, { status: 201 });
  } catch (error) {
    return Response.json(failure(error), { status: 409 });
  }
}
