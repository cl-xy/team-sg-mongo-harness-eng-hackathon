import { compareResponses, UpstreamError } from "@/lib/comparison";
export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(request: Request) {
  const apiUrl = process.env.MEMORY_API_URL;
  const apiKey = process.env.OPENROUTER_API_KEY;
  const model = process.env.OPENROUTER_MODEL;
  if (!apiUrl || !apiKey || !model)
    return Response.json(
      {
        error:
          "Live comparison needs MEMORY_API_URL, OPENROUTER_API_KEY and OPENROUTER_MODEL in frontend/.env.local. The recorded replay remains available.",
      },
      { status: 503 },
    );
  try {
    const text = await request.text();
    if (text.length > 24_000)
      return Response.json({ error: "Request is too large." }, { status: 413 });
    const body = JSON.parse(text);
    if (
      typeof body.prompt !== "string" ||
      !body.prompt.trim() ||
      body.prompt.length > 20_000 ||
      typeof body.session_id !== "string" ||
      !/^[A-Za-z0-9._:-]{1,160}$/.test(body.session_id) ||
      typeof body.request_id !== "string" ||
      !/^[A-Za-z0-9._:-]{1,160}$/.test(body.request_id)
    ) {
      return Response.json(
        {
          error:
            "Enter a prompt (up to 20,000 characters) and a valid session ID.",
        },
        { status: 400 },
      );
    }
    const result = await compareResponses(
      { ...body, prompt: body.prompt.trim() },
      { apiUrl, apiKey, model },
    );
    return Response.json(result);
  } catch (error) {
    if (error instanceof SyntaxError)
      return Response.json(
        { error: "Request must be valid JSON." },
        { status: 400 },
      );
    console.error("evaluate error:", error);
    const message =
      error instanceof UpstreamError
        ? error.message
        : `${error instanceof Error ? error.message : "Unknown error"}`;
    return Response.json(
      { error: message },
      { status: error instanceof UpstreamError ? error.status : 502 },
    );
  }
}
