"""Makes pip-installed NVIDIA CUDA/cuDNN DLLs discoverable on Windows.

`ctranslate2`'s GPU path needs cuBLAS/cuDNN shared libraries at runtime. On
Linux those ship as .so files next to the importing extension and are found
automatically; on Windows, Python 3.8+ no longer searches PATH for a C
extension's DLL dependencies (a security hardening change), so a DLL
installed by the `nvidia-cudnn-cu12` / `nvidia-cublas-cu12` pip packages
(under `.../site-packages/nvidia/<pkg>/bin/*.dll`) is invisible to
ctranslate2 unless we explicitly register its directory with
`os.add_dll_directory`.

Without this, GPU transcription doesn't fail gracefully — it hard-crashes
the whole process with an unrecoverable native "could not locate
cudnn_ops64_9.dll" fault that Python's own exception handling cannot catch.
This module (imported before ctranslate2 anywhere in the app) is what
prevents that: see hardware/detector.py and transcription/whisper_engine.py.
"""

from __future__ import annotations

import logging
import os
import site
import sys
from pathlib import Path

logger = logging.getLogger("meetnote.cuda_env")

_configured = False


def configure_cuda_dll_search_path() -> list[str]:
    global _configured
    if _configured or sys.platform != "win32":
        return []
    _configured = True

    added: list[str] = []
    candidate_roots = list(site.getsitepackages())
    try:
        candidate_roots.append(site.getusersitepackages())
    except Exception:
        pass

    for root in candidate_roots:
        nvidia_dir = Path(root) / "nvidia"
        if not nvidia_dir.is_dir():
            continue
        for pkg_dir in nvidia_dir.iterdir():
            for sub in ("bin", "lib"):
                candidate = pkg_dir / sub
                if candidate.is_dir():
                    try:
                        os.add_dll_directory(str(candidate))
                    except OSError as exc:
                        logger.warning("Could not register DLL directory %s: %s", candidate, exc)
                    added.append(str(candidate))

    if added:
        # os.add_dll_directory alone is not enough in practice: cuDNN 9's
        # own internal plugin loader (cudnn64_9.dll loading
        # cudnn_ops64_9.dll etc.) does a classic LoadLibrary lookup that
        # only honors PATH, not the AddDllDirectory list — that call happens
        # inside NVIDIA's DLL, outside Python's or ctranslate2's control.
        # Prepending to PATH covers that case too.
        os.environ["PATH"] = os.pathsep.join(added) + os.pathsep + os.environ.get("PATH", "")

    if added:
        logger.info("Registered %d CUDA/cuDNN DLL director(ies) for GPU inference", len(added))
    return added
