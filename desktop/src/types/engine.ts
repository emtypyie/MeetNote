// Mirrors engine/*.py response shapes. Kept as one file since the engine is
// the single source of truth for all of this — see services/engineClient.ts.

export interface HardwareProfile {
  os: string;
  cpu_model: string;
  cpu_cores: number;
  cpu_logical: number;
  ram_total_gb: number;
  gpu_name: string | null;
  gpu_vram_mb: number | null;
  cuda_driver_present: boolean;
  cuda_usable: boolean;
  cuda_failure_reason: string | null;
  warnings: string[];
}

export interface TranscriptionMode {
  device: "cuda" | "cpu" | "error";
  model_size: string;
  compute_type: string;
  label: string;
  reason: string;
}

export interface WhisperStatus {
  loading: boolean;
  loaded: boolean;
  error: string | null;
  status: {
    model_size: string;
    device: string;
    compute_type: string;
    loaded: boolean;
    gpu_fallback_reason: string | null;
  } | null;
  restart_required?: boolean;
  saved_hardware_preference?: string;
  active_hardware_preference?: string;
}

export interface AudioDeviceProbe {
  microphone_ok: boolean;
  microphone_name: string | null;
  system_audio_ok: boolean;
  system_audio_name: string | null;
  error: string | null;
}

export type ConnectivityStatus =
  | "not_configured"
  | "checking"
  | "configured"
  | "auth_failed"
  | "unavailable"
  | "model_not_found"
  | "unknown";

export interface ProviderStatus {
  name: string;
  configured: boolean;
  status: ConnectivityStatus;
  error: string | null;
}

export interface AIProviderStatus {
  gemini: ProviderStatus;
  groq: ProviderStatus;
  primary: string | null;
  fallback: string | null;
}

export interface HealthResponse {
  os: string;
  hardware: HardwareProfile | null;
  transcription_mode: TranscriptionMode | null;
  whisper: WhisperStatus;
  audio_devices: AudioDeviceProbe;
  storage: { ok: boolean; error?: string };
  ai_providers: AIProviderStatus | null;
  active_meeting_id: string | null;
}

export interface MeetingSummary {
  meeting_id: string;
  title: string;
  meeting_dir: string;
  template_id: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  status: string;
  transcription_device: string | null;
  ai_provider_used: string | null;
  notes_status: string;
}

export interface Marker {
  offset_seconds: number;
  label: string;
  created_at: string;
}

export interface MeetingMetadata {
  meeting_id: string;
  title: string;
  template_id: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  last_completed_chunk: number;
  status: string;
  transcription_mode: Record<string, unknown>;
  markers: Marker[];
  ai_provider_used: string | null;
  notes_status: string;
  validation_warnings: string[];
}

export interface ChunkRecord {
  chunk_index: number;
  start_offset_seconds: number;
  end_offset_seconds: number;
  text: string;
  status: "completed" | "failed";
  device_used: string;
  mic_present: boolean;
  system_audio_present: boolean;
  error: string | null;
  completed_at: number;
}

export interface MeetingDetail {
  metadata: MeetingMetadata;
  chunks: ChunkRecord[];
}

export interface CurrentMeetingStatus {
  active: boolean;
  meeting_id?: string;
  state?: string;
  elapsed_seconds?: number;
  device_status?: DeviceStatus;
  pending_chunks?: number;
}

export interface DeviceStatus {
  microphone_connected: boolean;
  microphone_name: string | null;
  system_audio_connected: boolean;
  system_audio_name: string | null;
  last_error: string | null;
}

export interface NoteTemplate {
  id: string;
  name: string;
  sections: string[];
}

export interface AppConfig {
  default_template_id: string;
  startup_behavior: string;
  audio: {
    microphone_device_id: string | null;
    system_audio_device_id: string | null;
    input_gain: number;
    output_gain: number;
    chunk_seconds: number;
  };
  transcription?: {
    hardware_mode?: "automatic" | "gpu" | "cpu";
    output_language?: string;
  };
  ai: {
    primary_provider: string;
    fallback_provider: string;
    groq_model: string;
    gemini_model: string;
  };
  storage: {
    retention_days: number | null;
  };
  storage_root?: string;
  meetings_root?: string;
}

export type WSMessage =
  | { type: "snapshot"; active: boolean; meeting_id: string | null; state: string | null }
  | ({ type: "transcript_chunk" } & ChunkRecord)
  | { type: "state_changed"; state: string }
  | { type: "marker_added"; offset_seconds: number }
  | { type: "error"; message: string }
  | { type: "notes_generating"; meeting_id: string }
  | { type: "notes_ready"; meeting_id: string; provider_used: string; warnings: string[] }
  | { type: "notes_failed"; meeting_id: string; reason: string };
