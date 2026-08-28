// Thin HTTP client for the local Python engine. The engine's port is fixed
// (see src-tauri/src/lib.rs's ENGINE_PORT) but we still ask Tauri for it
// rather than hardcoding it a second time here.

import { invoke } from "@tauri-apps/api/core";
import type {
  AIProviderStatus,
  AppConfig,
  CurrentMeetingStatus,
  HealthResponse,
  MeetingDetail,
  MeetingMetadata,
  MeetingSummary,
  NoteTemplate,
} from "../types/engine";

let cachedPort: number | null = null;

export async function getEnginePort(): Promise<number> {
  if (cachedPort !== null) return cachedPort;
  cachedPort = await invoke<number>("engine_port");
  return cachedPort;
}

export async function engineBaseUrl(): Promise<string> {
  const port = await getEnginePort();
  return `http://127.0.0.1:${port}`;
}

export async function engineWsUrl(): Promise<string> {
  const port = await getEnginePort();
  return `ws://127.0.0.1:${port}/ws/meeting`;
}

class EngineUnavailableError extends Error {
  cause?: unknown;

  constructor(cause?: unknown) {
    super(
      "Could not reach the MeetNote engine. It may still be starting up, or failed to launch " +
        "— check engine/logs/engine.log.",
    );
    this.cause = cause;
  }
}

function isConnectionError(err: unknown): boolean {
  // Detect connection-related errors that warrant retrying
  if (err instanceof TypeError) {
    const msg = err.message.toLowerCase();
    return (
      msg.includes("failed to fetch") ||
      msg.includes("network") ||
      msg.includes("connection") ||
      msg.includes("refused")
    );
  }
  return false;
}

async function requestWithRetry<T>(
  path: string,
  init?: RequestInit,
  retryOptions?: { maxAttempts?: number; initialDelayMs?: number; maxDelayMs?: number },
): Promise<T> {
  const maxAttempts = retryOptions?.maxAttempts ?? 5;
  const initialDelayMs = retryOptions?.initialDelayMs ?? 500;
  const maxDelayMs = retryOptions?.maxDelayMs ?? 2000;

  let lastError: unknown;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const base = await engineBaseUrl();
      const res = await fetch(`${base}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      });

      if (!res.ok) {
        let detail = res.statusText;
        try {
          const body = await res.json();
          detail = body.detail ?? detail;
        } catch {
          // response body wasn't JSON; keep statusText
        }
        throw new Error(detail);
      }

      if (res.status === 204) return undefined as T;
      return (await res.json()) as T;
    } catch (err) {
      lastError = err;

      // Only retry on connection errors, not on HTTP errors or JSON parsing errors
      if (!isConnectionError(err)) {
        throw err;
      }

      if (attempt < maxAttempts) {
        // Exponential backoff: delay increases with each retry
        const delayMs = Math.min(initialDelayMs * Math.pow(2, attempt - 1), maxDelayMs);
        console.debug(`Engine connection failed (attempt ${attempt}/${maxAttempts}), retrying in ${delayMs}ms...`);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
  }

  // All retries exhausted
  throw new EngineUnavailableError(lastError);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return requestWithRetry(path, init);
}

export const engineClient = {
  health: () => request<HealthResponse>("/health"),

  getConfig: () => request<AppConfig>("/config"),
  patchConfig: (patch: Partial<AppConfig>) =>
    request<AppConfig>("/config", { method: "POST", body: JSON.stringify(patch) }),

  listTemplates: () => request<NoteTemplate[]>("/templates"),
  saveTemplate: (template: NoteTemplate) =>
    request<NoteTemplate>("/templates", { method: "POST", body: JSON.stringify(template) }),
  deleteTemplate: (id: string) => request<{ deleted: boolean }>(`/templates/${id}`, { method: "DELETE" }),

  listMeetings: () => request<MeetingSummary[]>("/meetings"),
  listUnfinished: () => request<MeetingMetadata[]>("/meetings/unfinished"),
  getMeeting: (id: string) => request<MeetingDetail>(`/meetings/${id}`),

  currentMeeting: () => request<CurrentMeetingStatus>("/meeting/current"),
  startMeeting: (title: string, templateId: string) =>
    request<{ meeting_id: string }>("/meeting/start", {
      method: "POST",
      body: JSON.stringify({ title, template_id: templateId }),
    }),
  pauseMeeting: () => request<{ state: string }>("/meeting/pause", { method: "POST" }),
  resumeMeeting: () => request<{ state: string }>("/meeting/resume", { method: "POST" }),
  stopMeeting: () =>
    request<{ meeting_id: string; duration_seconds: number }>("/meeting/stop", { method: "POST" }),
  markImportant: () => request<{ offset_seconds: number }>("/meeting/mark-important", { method: "POST" }),

  retryGenerateNotes: (id: string) => request<{ ok: boolean }>(`/meetings/${id}/generate-notes`, { method: "POST" }),
  abandonMeeting: (id: string) => request<{ ok: boolean }>(`/meetings/${id}/abandon`, { method: "POST" }),
  resumeAfterRestart: (id: string) =>
    request<{ meeting_id: string; resumed_from_chunk: number }>(`/meetings/${id}/resume-after-restart`, {
      method: "POST",
    }),

  recheckAIProviders: () => request<AIProviderStatus>("/ai/recheck", { method: "POST" }),

  exportPath: (id: string, fmt: "txt" | "md") => request<{ path: string }>(`/meetings/${id}/export/${fmt}`),
  notesText: (id: string) => request<{ text: string | null }>(`/meetings/${id}/notes-text`),
  transcriptPath: (id: string) => request<{ path: string }>(`/meetings/${id}/transcript-path`),
  folderPath: (id: string) => request<{ path: string }>(`/meetings/${id}/folder-path`),
  deleteMeeting: (id: string) => request<{ success: boolean; meeting_id: string }>(`/meetings/${id}`, { method: "DELETE" }),
};

export { EngineUnavailableError };
