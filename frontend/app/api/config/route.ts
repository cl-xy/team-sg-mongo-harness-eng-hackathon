export const dynamic = "force-dynamic";
export function GET() {
  return Response.json({
    memory_api: Boolean(process.env.MEMORY_API_URL),
    model: Boolean(
      process.env.OPENROUTER_API_KEY && process.env.OPENROUTER_MODEL,
    ),
    model_name: process.env.OPENROUTER_MODEL || null,
  });
}
