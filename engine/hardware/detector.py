"""Automatic hardware detection.

Detects CPU, RAM and GPU/CUDA, and — critically — actually verifies CUDA
inference is *usable* by the installed ctranslate2 build rather than just
checking that an NVIDIA GPU exists (a GPU can be present while the CUDA
runtime libraries ctranslate2 needs are missing or mismatched). The result
feeds hardware/model_selector.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import psutil

from cuda_env import configure_cuda_dll_search_path
from os_detect import OperatingSystem, detect_os, os_display_name

logger = logging.getLogger("meetnote.hardware")


@dataclass
class HardwareProfile:
    os_name: str
    os_kind: OperatingSystem
    cpu_model: str
    cpu_cores: int
    cpu_logical: int
    ram_total_gb: float
    gpu_name: Optional[str] = None
    gpu_vram_mb: Optional[int] = None
    cuda_driver_present: bool = False
    cuda_usable: bool = False
    cuda_failure_reason: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "os": self.os_name,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "cpu_logical": self.cpu_logical,
            "ram_total_gb": round(self.ram_total_gb, 1),
            "gpu_name": self.gpu_name,
            "gpu_vram_mb": self.gpu_vram_mb,
            "cuda_driver_present": self.cuda_driver_present,
            "cuda_usable": self.cuda_usable,
            "cuda_failure_reason": self.cuda_failure_reason,
            "warnings": self.warnings,
        }


def _cpu_model_name() -> str:
    try:
        import platform as _platform

        name = _platform.processor()
        if name:
            return name
    except Exception:  # pragma: no cover - defensive
        pass
    return "Unknown CPU"


def _detect_gpu() -> tuple[Optional[str], Optional[int], bool, list[str]]:
    """Detect NVIDIA GPU presence + VRAM via NVML.

    Returns (gpu_name, vram_mb, driver_present, warnings). This step only
    tells us a GPU *exists* — whether ctranslate2 can actually use it is
    checked separately in `_check_cuda_usable`, because that's the question
    that actually matters for choosing GPU vs CPU mode.
    """
    warnings: list[str] = []
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            count = pynvml.nvmlDeviceGetCount()
            if count == 0:
                return None, None, False, warnings
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            vram_mb = int(mem.total / (1024 * 1024))
            return name, vram_mb, True, warnings
        finally:
            pynvml.nvmlShutdown()
    except Exception as exc:  # NVML not installed, no driver, no GPU, etc.
        warnings.append(f"NVIDIA GPU not detected via NVML: {exc}")
        return None, None, False, warnings


def _check_cuda_usable(gpu_present: bool) -> tuple[bool, Optional[str]]:
    """Actually attempt a CUDA init through ctranslate2, the library
    faster-whisper uses for inference. This catches the common real-world
    failure mode where nvidia-smi shows a GPU but the CUDA/cuDNN runtime
    ctranslate2 needs isn't actually loadable (missing DLLs/.so, driver too
    old, wrong ctranslate2 build, etc.) — exactly the case the product spec
    calls out: don't just check GPU existence, check genuine usability.
    """
    if not gpu_present:
        return False, "No NVIDIA GPU detected"
    try:
        configure_cuda_dll_search_path()
        import ctranslate2

        device_count = ctranslate2.get_cuda_device_count()
        if device_count < 1:
            return False, "ctranslate2 reports 0 usable CUDA devices"
        # This call touches the CUDA runtime/cuDNN and will raise if the
        # libraries required for GPU inference aren't actually loadable.
        ctranslate2.get_supported_compute_types("cuda", 0)
        return True, None
    except Exception as exc:
        return False, f"ctranslate2 could not initialize CUDA: {exc}"


def detect_hardware(skip_cuda_check: bool = False) -> HardwareProfile:
    os_kind = detect_os()
    vm = psutil.virtual_memory()
    gpu_name, gpu_vram_mb, driver_present, gpu_warnings = _detect_gpu()
    
    if skip_cuda_check:
        cuda_usable, cuda_failure_reason = False, "Skipped because CPU-only mode is selected"
    else:
        cuda_usable, cuda_failure_reason = _check_cuda_usable(driver_present)

    profile = HardwareProfile(
        os_name=os_display_name(),
        os_kind=os_kind,
        cpu_model=_cpu_model_name(),
        cpu_cores=psutil.cpu_count(logical=False) or psutil.cpu_count() or 1,
        cpu_logical=psutil.cpu_count(logical=True) or 1,
        ram_total_gb=vm.total / (1024**3),
        gpu_name=gpu_name,
        gpu_vram_mb=gpu_vram_mb,
        cuda_driver_present=driver_present,
        cuda_usable=cuda_usable,
        cuda_failure_reason=cuda_failure_reason,
        warnings=gpu_warnings,
    )

    if driver_present and not cuda_usable and not skip_cuda_check:
        logger.warning(
            "GPU detected (%s) but CUDA inference is not usable: %s",
            gpu_name,
            cuda_failure_reason,
        )
    return profile
