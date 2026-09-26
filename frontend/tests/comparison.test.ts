import test from "node:test";
import assert from "node:assert/strict";
import {
  compareResponses,
  MemoryClient,
  UpstreamError,
} from "../lib/comparison";

const context = {
  seed_ids: ["n1"],
  source_ids: ["old-source"],
  nodes: [],
  edges: [],
  context_text: "Older noise complaints [old-source]",
  token_count: 9,
  truncated: false,
};

test("uses PR #4 routes, identical history and model settings, and adds memory only to our response", async () => {
  const requests: { url: string; body: any }[] = [];
  const modelRequests: any[] = [];
  const mockFetch: typeof fetch = async (input, init) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    requests.push({ url, body });
    if (url.includes("openrouter.ai")) {
      modelRequests.push(body);
      return Response.json({
        choices: [{ message: { content: "Investigate the reports." } }],
        usage: { prompt_tokens: 15, completion_tokens: 6 },
      });
    }
    if (url.includes("/messages?"))
      return Response.json({
        messages: [
          { role: "user", content: "Earlier question" },
          { role: "assistant", content: "Earlier answer" },
        ],
      });
    if (url.endsWith("/context")) return Response.json(context);
    if (url.endsWith("/response"))
      return Response.json({ message: { content: body.content } });
    if (url.endsWith("/turns")) return Response.json({ turn_id: "turn-1" });
    throw new Error(`Unexpected URL ${url}`);
  };
  const result = await compareResponses(
    { prompt: "What changed?", session_id: "demo", request_id: "request-1" },
    {
      apiUrl: "http://memory.test",
      apiKey: "test-key",
      model: "test-model",
      fetcher: mockFetch,
    },
  );
  assert.equal(modelRequests.length, 2);
  assert.deepEqual(
    modelRequests[0].messages.slice(1),
    modelRequests[1].messages.slice(1),
  );
  assert.equal(modelRequests[0].model, modelRequests[1].model);
  assert.equal(modelRequests[0].temperature, modelRequests[1].temperature);
  assert.ok(
    !modelRequests[0].messages[0].content.includes(context.context_text),
  );
  assert.ok(
    modelRequests[1].messages[0].content.includes(context.context_text),
  );
  assert.equal(requests.filter((r) => r.url.endsWith("/context")).length, 1);
  assert.equal(requests.filter((r) => r.url.endsWith("/response")).length, 2);
  assert.deepEqual(result.baseline.historical_source_ids, []);
  assert.deepEqual(result.memory.historical_source_ids, ["old-source"]);
  assert.equal(result.memory.input_tokens, 15);
});

test("surfaces upstream conflicts without substituting demo data", async () => {
  const client = new MemoryClient("http://memory.test", async () =>
    Response.json({ error: "idempotency conflict" }, { status: 409 }),
  );
  await assert.rejects(
    () => client.request("POST", "/v1/sessions/demo/turns", {}),
    (error: unknown) => error instanceof UpstreamError && error.status === 409,
  );
});

test("rejects malformed retrieval payloads before calling the model", async () => {
  const mockFetch: typeof fetch = async (input) => {
    if (String(input).includes("/messages?"))
      return Response.json({ messages: [] });
    if (String(input).endsWith("/context"))
      return Response.json({ wrong: true });
    return Response.json({ turn_id: "turn-1" });
  };
  await assert.rejects(
    () =>
      compareResponses(
        { prompt: "Question", session_id: "demo", request_id: "request-2" },
        {
          apiUrl: "http://memory.test",
          apiKey: "x",
          model: "model",
          fetcher: mockFetch,
        },
      ),
    /retrieval payload/,
  );
});
