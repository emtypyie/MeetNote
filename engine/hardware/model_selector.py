"""Select a Whisper model + device + compute type from a HardwareProfile.

Thresholds live in model_profiles.json (a data file, not hardcoded branches)
so they can be retuned after real benchmarking without touching code, per
the product spec's explicit instruction not to hardcode these numbers
blindly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hardware.detector import HardwareProfile

_PROFILES_PATH = Path(__file__).parent / "model_profiles.json"


@dataclass
class TranscriptionModeDecision:
    device: str  # "cuda" | "cpu"
    model_size: str
    compute_type: str
    label: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "model_size": self.model_size,
            "compute_type": self.compute_type,
            "label": self.label,
            "reason": self.reason,
        }


def _load_profiles() -> dict:
    with open(_PROFILES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def select_transcription_mode(
    profile: HardwareProfile, user_preference: str = "automatic", profiles: dict | None = None
) -> TranscriptionModeDecision:
    profiles = profiles or _load_profiles()

    if user_preference in ("automatic", "gpu"):
        if profile.cuda_usable:
            vram = profile.gpu_vram_mb or 0
            for rule in profiles["gpu_rules"]:
                if vram >= rule["min_vram_mb"]:
                    return TranscriptionModeDecision(
                        device="cuda",
                        model_size=rule["model"],
                        compute_type=rule["compute_type"],
                        label=rule["label"],
                        reason=f"CUDA usable on {profile.gpu_name} ({vram} MB VRAM)",
                    )
        elif user_preference == "gpu":
            # Explicitly requested GPU, but it's not usable. Don't fall back to CPU silently.
            return TranscriptionModeDecision(
                device="error",
                model_size="",
                compute_type="",
                label="GPU unavailable",
                reason=profile.cuda_failure_reason or "NVIDIA GPU not detected or usable.",
            )

    # CPU path — either user requested CPU, no usable CUDA on automatic, or no gpu_rule matched.
    for rule in profiles["cpu_rules"]:
        if (
            profile.ram_total_gb >= rule["min_ram_gb"]
            and profile.cpu_logical >= rule["min_cpu_cores"]
        ):
            reason = (
                profile.cuda_failure_reason
                if profile.cuda_driver_present
                else "No usable NVIDIA GPU detected"
            )
            return TranscriptionModeDecision(
                device="cpu",
                model_size=rule["model"],
                compute_type=rule["compute_type"],
                label=rule["label"],
                reason=reason or "CPU mode",
            )

    # Should be unreachable — the last cpu_rule has min_ram_gb=0/min_cpu_cores=0
    # and always matches — but never leave the caller without a decision.
    return TranscriptionModeDecision(
        device="cpu",
        model_size="base",
        compute_type="int8",
        label="Fallback CPU configuration",
        reason="No model profile matched; using safe default",
    )
