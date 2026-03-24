async function parseError(res) {
  try {
    const t = await res.text();
    return t || res.statusText;
  } catch {
    return res.statusText;
  }
}

/** @returns {Promise<{ status: string, llm_max_retries?: number, llm_parse_waves?: number, llm_provider?: string, openrouter_ready?: boolean }>} */
export async function fetchHealth() {
  const res = await fetch("/health");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/**
 * @returns {Promise<{
 *   llm_provider: string,
 *   llama_cpp_url: string,
 *   llama_completion_path: string,
 *   llm_api_style: string,
 *   llm_openai_model: string,
 *   openrouter_base_url: string,
 *   openrouter_model: string,
 *   openrouter_ready: boolean,
 *   has_openrouter_api_key: boolean,
 *   has_llm_bearer: boolean,
 *   llm_timeout_sec: number,
 * }>}
 */
export async function fetchPublicSettings() {
  const res = await fetch("/settings/public");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/**
 * @returns {Promise<{
 *   ok: boolean,
 *   latency_ms: number,
 *   llm_provider: string,
 *   response_preview?: string,
 *   error?: string,
 *   detail?: string,
 * }>}
 */
export async function postTestLlm() {
  const res = await fetch("/settings/test-llm", { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchSessions() {
  const res = await fetch("/sessions");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchSession(sessionId) {
  const res = await fetch(`/session/${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/**
 * @param {string} sessionId
 * @param {{ choice?: string, free_text?: string }} [payload]
 */
export async function postAction(sessionId, payload = {}) {
  const choice = payload.choice ?? "";
  const free_text = payload.free_text ?? "";
  const res = await fetch(`/session/${encodeURIComponent(sessionId)}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choice, free_text }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/**
 * NDJSON stream: progress events then final ActionResponse-shaped JSON.
 * @param {string} sessionId
 * @param {{ choice?: string, free_text?: string }} [payload]
 * @param {(ev: { type: string, current?: number, max?: number, wave?: number, max_waves?: number }) => void} [onProgress]
 */
export async function postActionStream(sessionId, payload = {}, onProgress) {
  const choice = payload.choice ?? "";
  const free_text = payload.free_text ?? "";
  const res = await fetch(`/session/${encodeURIComponent(sessionId)}/action/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson, application/json",
    },
    body: JSON.stringify({ choice, free_text }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const reader = res.body?.getReader();
  if (!reader) throw new Error("no response body");

  const decoder = new TextDecoder();
  let buf = "";
  /** @type {Record<string, unknown> | null} */
  let finalPayload = null;

  function consumeLines() {
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const ev = JSON.parse(line);
      if (ev.type === "llm_attempt" && onProgress) onProgress(ev);
      if (ev.type === "result") finalPayload = ev.payload;
      if (ev.type === "error") throw new Error(ev.message || "stream error");
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    if (value) buf += decoder.decode(value, { stream: true });
    consumeLines();
    if (done) break;
  }

  if (!finalPayload) throw new Error("incomplete stream");
  return finalPayload;
}

/**
 * @param {string} sessionId
 * @param {boolean} [overwrite]
 * @param {{ language?: 'en'|'ru', player?: {name?: string, backstory?: string}, world?: {location?: string, premise?: string} }} [setup]
 */
export async function createSession(sessionId, overwrite = false, setup = {}) {
  const payload = {
    session_id: sessionId,
    overwrite,
    language: setup.language || "en",
    player: setup.player || undefined,
    world: setup.world || undefined,
  };
  const res = await fetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await parseError(res);
    const err = new Error(res.status === 409 ? `409: ${detail}` : detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}
