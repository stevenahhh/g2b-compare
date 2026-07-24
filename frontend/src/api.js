export class ApiError extends Error {
  constructor(message, { status = 0, offline = false, body = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.offline = offline;
    this.body = body;
  }
}

async function responseBody(response) {
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") ?? "";
  return contentType.includes("application/json")
    ? response.json()
    : response.text();
}

export async function requestJson(path, options = {}, fetchImplementation = globalThis.fetch) {
  let response;
  try {
    response = await fetchImplementation(path, {
      ...options,
      headers: { Accept: "application/json", ...options.headers },
    });
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : "Network request failed", {
      offline: true,
    });
  }

  const body = await responseBody(response);
  if (!response.ok) {
    const message = body?.error ?? body?.detail ?? `HTTP ${response.status}`;
    throw new ApiError(String(message), { status: response.status, body });
  }
  return body;
}
