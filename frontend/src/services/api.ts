import type { QuoteProcessResponse } from "../types/quote";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function friendlyMessage(status: number, detail: string): string {
  const lower = detail.toLowerCase();
  if (status === 503 || lower.includes("ai matching is enabled but no provider")) {
    return "AI matching is currently unavailable. Turn off AI matching and try again, or contact your administrator.";
  }
  if (status === 413) {
    return "This file is too large to upload. Choose a smaller Excel quote.";
  }
  if (status === 400 && lower.includes("xlsx")) {
    return "Only .xlsx Excel files are supported.";
  }
  if (status === 400) {
    return "Unable to process this file. Please verify that it is a valid Excel quote.";
  }
  if (status === 0) {
    return "The QuoteIQ service is unavailable. Confirm the backend is running and try again.";
  }
  return "Unable to process this file. Please verify that it is a valid Excel quote.";
}

function apiUrl(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  const raw = String(import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/$/, "");
  // During Vite dev/test, always call same-origin /api so the proxy forwards
  // to the backend. A full http(s) base bypasses the proxy and often fails with
  // a TypeError (CORS or localhost vs 127.0.0.1), which was shown as "unavailable".
  if (import.meta.env.DEV || !raw || raw.startsWith("/")) {
    return suffix;
  }
  return `${raw}${suffix}`;
}

async function readError(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") {
        return friendlyMessage(response.status, detail);
      }
    }
  } catch {
    /* ignore non-JSON errors */
  }
  return friendlyMessage(response.status, "");
}

function buildForm(file: File, useAI: boolean): FormData {
  const form = new FormData();
  form.append("file", file);
  form.append("use_ai", useAI ? "true" : "false");
  return form;
}

function asProcessResponse(body: unknown): QuoteProcessResponse {
  if (!body || typeof body !== "object") {
    throw new ApiError("Unable to process this file. Please verify that it is a valid Excel quote.", 200);
  }
  const payload = body as Partial<QuoteProcessResponse>;
  if (!payload.summary || !Array.isArray(payload.results)) {
    throw new ApiError("Unable to process this file. Please verify that it is a valid Excel quote.", 200);
  }
  return payload as QuoteProcessResponse;
}

async function postForm(path: string, file: File, useAI: boolean): Promise<Response> {
  try {
    return await fetch(apiUrl(path), {
      method: "POST",
      body: buildForm(file, useAI),
    });
  } catch {
    throw new ApiError(friendlyMessage(0, ""), 0);
  }
}

export async function processQuote(file: File, useAI: boolean): Promise<QuoteProcessResponse> {
  const response = await postForm("/api/quote/process/results", file, useAI);
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  try {
    return asProcessResponse(await response.json());
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError("Unable to process this file. Please verify that it is a valid Excel quote.", response.status);
  }
}

export async function processQuoteCsv(file: File, useAI: boolean): Promise<Blob> {
  const response = await postForm("/api/quote/process", file, useAI);
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  return response.blob();
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
