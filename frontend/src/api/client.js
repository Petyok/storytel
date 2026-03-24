async function parseError(res) {
  try {
    const t = await res.text();
    return t || res.statusText;
  } catch {
    return res.statusText;
  }
}

/** @returns {Promise<{ status: string, llm_max_retries?: number }>} */
export async function fetchHealth() {
  const res = await fetch("/health");
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
