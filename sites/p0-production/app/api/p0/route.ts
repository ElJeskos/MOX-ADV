import { applyAction, overview, userKey } from "../../../lib/p0";

function message(error: unknown) {
  return error instanceof Error ? error.message : "Production-модуль завершил действие fail closed.";
}

export async function GET(request: Request) {
  try {
    return Response.json(await overview(userKey(request)));
  } catch (error) {
    return Response.json({ error: message(error) }, { status: 503 });
  }
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as Record<string, unknown>;
    return Response.json(await applyAction(userKey(request), payload), { status: 201 });
  } catch (error) {
    return Response.json({ error: message(error) }, { status: 409 });
  }
}
