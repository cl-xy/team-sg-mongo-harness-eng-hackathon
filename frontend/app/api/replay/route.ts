import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
export const runtime = "nodejs";
export const maxDuration = 30;
const execute = promisify(execFile);

export async function POST() {
  const root = path.resolve(process.cwd(), "..");
  const localPython = path.join(root, ".venv-memory/bin/python");
  const python =
    process.env.DASHBOARD_PYTHON ||
    (existsSync(localPython) ? localPython : "python3");
  try {
    const { stdout } = await execute(
      python,
      ["-m", "scripts.dashboard_snapshot"],
      { cwd: root, timeout: 25_000, maxBuffer: 8 * 1024 * 1024 },
    );
    return Response.json(JSON.parse(stdout));
  } catch {
    return Response.json(
      {
        error:
          "Replay could not run. Install the Python project dependencies and set DASHBOARD_PYTHON to that interpreter. Your recorded snapshot is still available.",
      },
      { status: 503 },
    );
  }
}
