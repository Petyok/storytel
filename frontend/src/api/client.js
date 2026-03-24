async function parseError(res) {
  try {
    const t = await res.text();
    return t || res.statusText;
  } catch {
    return res.statusText;
  }
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

export async function postAction(sessionId, choice) {
  const res = await fetch(`/session/${encodeURIComponent(sessionId)}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choice }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/**
 * @param {string} sessionId
 * @param {boolean} [overwrite]
 */
export async function createSession(sessionId, overwrite = false) {
  const res = await fetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, overwrite }),
  });
  if (!res.ok) {
    const detail = await parseError(res);
    const err = new Error(res.status === 409 ? `409: ${detail}` : detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}
