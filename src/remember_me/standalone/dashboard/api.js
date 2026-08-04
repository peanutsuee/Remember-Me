// SPDX-License-Identifier: CPAL-1.0

const API_ROOT = "/api/v1";
const TOKEN_KEY = "remember_me_session_token";

export class ApiError extends Error {
  constructor(code, message, requestId, status) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.requestId = requestId;
    this.status = status;
  }
}

export function getSessionToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setSessionToken(token) {
  const value = String(token || "").trim();
  try {
    if (value) {
      sessionStorage.setItem(TOKEN_KEY, value);
    } else {
      sessionStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    return;
  }
}

export function clearSessionToken() {
  setSessionToken("");
}

function requestHeaders(authenticated, initialHeaders) {
  const headers = new Headers(initialHeaders || {});
  if (authenticated) {
    const token = getSessionToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

async function parseError(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const error = payload && payload.error ? payload.error : {};
  return new ApiError(
    error.code || "http_error",
    error.message || "The request could not be completed.",
    error.request_id || response.headers.get("X-Request-ID") || "",
    response.status,
  );
}

async function apiRequest(path, options = {}) {
  const authenticated = options.authenticated !== false;
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: requestHeaders(authenticated, options.headers),
    body: options.body,
    credentials: "omit",
    cache: "no-store",
  });
  if (!response.ok) {
    const error = await parseError(response);
    if (authenticated && response.status === 401) {
      clearSessionToken();
      window.dispatchEvent(
        new CustomEvent("remember-me-auth-required", {
          detail: { code: "authentication_required" },
        }),
      );
    }
    throw error;
  }
  if (options.responseType === "blob") {
    return response.blob();
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

export function getAbout() {
  return apiRequest(`${API_ROOT}/about`, { authenticated: false });
}

export function searchAssets(filters) {
  const params = new URLSearchParams();
  if (filters.query) {
    params.set("query", filters.query);
  }
  for (const tag of filters.tags) {
    params.append("tag", tag);
  }
  if (filters.mimeType) {
    params.set("mime_type", filters.mimeType);
  }
  if (filters.createdFrom) {
    params.set("created_from", filters.createdFrom);
  }
  if (filters.createdTo) {
    params.set("created_to", filters.createdTo);
  }
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));
  return apiRequest(`${API_ROOT}/assets?${params.toString()}`);
}

export function getAsset(assetId) {
  return apiRequest(`${API_ROOT}/assets/${encodeURIComponent(assetId)}`);
}

export function getAssetBlob(assetId) {
  return apiRequest(
    `${API_ROOT}/assets/${encodeURIComponent(assetId)}/content`,
    { responseType: "blob" },
  );
}

export function uploadAsset(file, metadata) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("expected_bytes", String(file.size));
  form.append("filename", file.name);
  form.append("mime_type", file.type || "application/octet-stream");
  form.append("title", metadata.title);
  form.append("description", metadata.description);
  for (const tag of metadata.tags) {
    form.append("tag", tag);
  }
  return apiRequest(`${API_ROOT}/assets`, {
    method: "POST",
    body: form,
  });
}

export function updateAsset(assetId, changes) {
  return apiRequest(`${API_ROOT}/assets/${encodeURIComponent(assetId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
}

export function deleteAsset(assetId) {
  return apiRequest(`${API_ROOT}/assets/${encodeURIComponent(assetId)}`, {
    method: "DELETE",
  });
}
