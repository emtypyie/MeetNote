from hardware.detector import HardwareProfile
from hardware.model_selector import select_transcription_mode
from os_detect import OperatingSystem


def _profile(**overrides) -> HardwareProfile:
    base = dict(
        os_name="Windows 11",
        os_kind=OperatingSystem.WINDOWS,
        cpu_model="Test CPU",
        cpu_cores=4,
        cpu_logical=8,
        ram_total_gb=16.0,
        gpu_name=None,
        gpu_vram_mb=None,
        cuda_driver_present=False,
        cuda_usable=False,
        cuda_failure_reason=None,
    )
    base.update(overrides)
    return HardwareProfile(**base)


def test_high_end_gpu_picks_medium_fp16():
    profile = _profile(
        gpu_name="RTX 4060", gpu_vram_mb=8188, cuda_driver_present=True, cuda_usable=True
    )
    decision = select_transcription_mode(profile)
    assert decision.device == "cuda"
    assert decision.model_size == "medium"
    assert decision.compute_type == "float16"


def test_mid_range_gpu_picks_small():
    profile = _profile(
        gpu_name="GTX 1650", gpu_vram_mb=4000, cuda_driver_present=True, cuda_usable=True
    )
    decision = select_transcription_mode(profile)
    assert decision.device == "cuda"
    assert decision.model_size == "small"


def test_gpu_present_but_cuda_unusable_falls_back_to_cpu():
    profile = _profile(
        gpu_name="RTX 4060",
        gpu_vram_mb=8188,
        cuda_driver_present=True,
        cuda_usable=False,
        cuda_failure_reason="cuDNN not found",
    )
    decision = select_transcription_mode(profile)
    assert decision.device == "cpu"
    assert decision.compute_type == "int8"
    assert "cuDNN" in decision.reason


def test_capable_cpu_only_system():
    profile = _profile(ram_total_gb=16.0, cpu_logical=8)
    decision = select_transcription_mode(profile)
    assert decision.device == "cpu"
    assert decision.model_size == "small"


def test_modest_cpu_only_system():
    profile = _profile(ram_total_gb=4.0, cpu_logical=2)
    decision = select_transcription_mode(profile)
    assert decision.device == "cpu"
    assert decision.model_size == "base"


def test_explicit_gpu_success():
    profile = _profile(
        gpu_name="RTX 4060", gpu_vram_mb=8188, cuda_driver_present=True, cuda_usable=True
    )
    decision = select_transcription_mode(profile, user_preference="gpu")
    assert decision.device == "cuda"


def test_explicit_gpu_fails_if_unusable():
    profile = _profile(
        gpu_name="RTX 4060",
        gpu_vram_mb=8188,
        cuda_driver_present=True,
        cuda_usable=False,
        cuda_failure_reason="cuDNN not found",
    )
    decision = select_transcription_mode(profile, user_preference="gpu")
    # Shouldn't fall back to CPU if they explicitly demanded GPU
    assert decision.device == "error"
    assert "cuDNN" in decision.reason


def test_explicit_cpu_overrides_usable_gpu():
    profile = _profile(
        gpu_name="RTX 4090", gpu_vram_mb=24000, cuda_driver_present=True, cuda_usable=True,
        ram_total_gb=32.0, cpu_logical=16
    )
    decision = select_transcription_mode(profile, user_preference="cpu")
    # Even though GPU is amazing, user said CPU
    assert decision.device == "cpu"
    assert decision.model_size == "small"
