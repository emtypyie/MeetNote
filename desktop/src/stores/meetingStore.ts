import { create } from "zustand";
import { engineClient } from "../services/engineClient";
import { engineSocket } from "../services/engineSocket";
import type { ChunkRecord, DeviceStatus, Marker, WSMessage } from "../types/engine";

interface MeetingState {
  meetingId: string | null;
  title: string;
  state: string; // MeetingState value from the engine
  elapsedSeconds: number;
  deviceStatus: DeviceStatus | null;
  chunks: ChunkRecord[];
  markers: Marker[];
  pendingChunks: number;
  lastError: string | null;
  socketConnected: boolean;

  hydrateFromCurrent: () => Promise<boolean>;
  start: (title: string, templateId: string) => Promise<string>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  stop: () => Promise<string>;
  markImportant: () => Promise<void>;
  reset: () => void;
  tick: () => void;
  handleMessage: (msg: WSMessage) => void;
}

let tickInterval: ReturnType<typeof setInterval> | null = null;
let unsubscribeSocket: (() => void) | null = null;

export const useMeetingStore = create<MeetingState>((set, get) => ({
  meetingId: null,
  title: "",
  state: "idle",
  elapsedSeconds: 0,
  deviceStatus: null,
  chunks: [],
  markers: [],
  pendingChunks: 0,
  lastError: null,
  socketConnected: false,

  hydrateFromCurrent: async () => {
    const current = await engineClient.currentMeeting();
    if (!current.active || !current.meeting_id) {
      return false;
    }
    const detail = await engineClient.getMeeting(current.meeting_id);
    set({
      meetingId: current.meeting_id,
      title: detail.metadata.title,
      state: current.state ?? "recording",
      elapsedSeconds: current.elapsed_seconds ?? 0,
      deviceStatus: current.device_status ?? null,
      chunks: detail.chunks,
      markers: detail.metadata.markers,
      pendingChunks: current.pending_chunks ?? 0,
    });
    ensureLiveSubscriptions(set, get);
    return true;
  },

  start: async (title, templateId) => {
    const { meeting_id } = await engineClient.startMeeting(title, templateId);
    set({
      meetingId: meeting_id,
      title,
      state: "recording",
      elapsedSeconds: 0,
      chunks: [],
      markers: [],
      pendingChunks: 0,
      lastError: null,
    });
    ensureLiveSubscriptions(set, get);
    return meeting_id;
  },

  pause: async () => {
    const { state } = await engineClient.pauseMeeting();
    set({ state });
  },

  resume: async () => {
    const { state } = await engineClient.resumeMeeting();
    set({ state });
  },

  stop: async () => {
    const { meeting_id } = await engineClient.stopMeeting();
    set({ state: "finalizing" });
    return meeting_id;
  },

  markImportant: async () => {
    const { offset_seconds } = await engineClient.markImportant();
    set((s) => ({ markers: [...s.markers, { offset_seconds, label: "important", created_at: "" }] }));
  },

  reset: () => {
    if (tickInterval) {
      clearInterval(tickInterval);
      tickInterval = null;
    }
    set({
      meetingId: null,
      title: "",
      state: "idle",
      elapsedSeconds: 0,
      deviceStatus: null,
      chunks: [],
      markers: [],
      pendingChunks: 0,
      lastError: null,
    });
  },

  tick: () => {
    const { state } = get();
    if (state === "recording") {
      set((s) => ({ elapsedSeconds: s.elapsedSeconds + 1 }));
    }
  },

  handleMessage: (msg) => {
    switch (msg.type) {
      case "transcript_chunk": {
        const { type: _type, ...chunk } = msg;
        set((s) => ({
          chunks: [...s.chunks.filter((c) => c.chunk_index !== chunk.chunk_index), chunk].sort(
            (a, b) => a.chunk_index - b.chunk_index,
          ),
          pendingChunks: Math.max(0, s.pendingChunks - 1),
        }));
        break;
      }
      case "state_changed":
        set({ state: msg.state });
        break;
      case "marker_added":
        set((s) => ({
          markers: [...s.markers, { offset_seconds: msg.offset_seconds, label: "important", created_at: "" }],
        }));
        break;
      case "error":
        set({ lastError: msg.message });
        break;
      default:
        break;
    }
  },
}));

function ensureLiveSubscriptions(
  set: (partial: Partial<MeetingState>) => void,
  get: () => MeetingState,
) {
  if (!tickInterval) {
    tickInterval = setInterval(() => get().tick(), 1000);
  }
  if (!unsubscribeSocket) {
    engineSocket.connect();
    unsubscribeSocket = engineSocket.subscribe((msg) => get().handleMessage(msg));
    set({ socketConnected: true });
  }
}
