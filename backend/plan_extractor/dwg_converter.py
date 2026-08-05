# backend/plan_extractor/dwg_converter.py
# Stage 4 — DWG to DXF Conversion
#
# Uses LibreDWG's dwg2dxf CLI tool as a subprocess to convert DWG files to DXF.
# This is called as a subprocess ONLY — LibreDWG (GPL) is never linked directly.

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class ConversionResult:
    """Result of DWG-to-DXF conversion."""

    def __init__(
        self,
        success: bool,
        dxf_path: Optional[str] = None,
        error: Optional[str] = None,
        warnings: Optional[list[str]] = None,
    ):
        self.success = success
        self.dxf_path = dxf_path
        self.error = error
        self.warnings = warnings or []


def _find_dwg2dxf() -> Optional[str]:
    """Find the dwg2dxf executable on the system PATH."""
    # Try common names
    for name in ["dwg2dxf", "dwg2dxf.exe"]:
        path = shutil.which(name)
        if path:
            return path

    # Check common installation directories on Windows
    common_paths = [
        r"C:\Program Files\LibreDWG\dwg2dxf.exe",
        r"C:\Program Files (x86)\LibreDWG\dwg2dxf.exe",
        r"C:\LibreDWG\dwg2dxf.exe",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p

    # Check common Linux paths
    linux_paths = [
        "/usr/bin/dwg2dxf",
        "/usr/local/bin/dwg2dxf",
    ]
    for p in linux_paths:
        if os.path.isfile(p):
            return p

    return None


def convert_dwg_to_dxf(dwg_bytes: bytes, filename: str = "input.dwg") -> ConversionResult:
    """
    Convert a DWG file to DXF using LibreDWG's dwg2dxf command-line tool.

    Args:
        dwg_bytes: Raw bytes of the DWG file
        filename: Original filename for reference

    Returns:
        ConversionResult with path to temporary DXF file on success
    """
    warnings = []

    # ── Check if dwg2dxf is available ──
    dwg2dxf_path = _find_dwg2dxf()
    if not dwg2dxf_path:
        return ConversionResult(
            success=False,
            error=(
                "LibreDWG's dwg2dxf tool is not installed or not on PATH. "
                "DWG file conversion requires LibreDWG to be installed as a system package. "
                "On Ubuntu/Debian: sudo apt-get install libredwg-tools. "
                "On Windows: download from https://github.com/LibreDWG/libredwg/releases. "
                "The DWG file cannot be processed without this tool."
            ),
            warnings=warnings,
        )

    # ── Write DWG bytes to a temp file ──
    temp_dir = tempfile.mkdtemp(prefix="firerulx_dwg_")
    dwg_path = os.path.join(temp_dir, filename)
    dxf_path = os.path.join(temp_dir, Path(filename).stem + ".dxf")

    try:
        with open(dwg_path, "wb") as f:
            f.write(dwg_bytes)

        # ── Run dwg2dxf ──
        try:
            proc = subprocess.run(
                [dwg2dxf_path, dwg_path],
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
                cwd=temp_dir,
            )

            if proc.stderr:
                stderr_text = proc.stderr.strip()
                if stderr_text:
                    warnings.append(f"dwg2dxf stderr: {stderr_text[:500]}")

            if proc.returncode != 0:
                return ConversionResult(
                    success=False,
                    error=(
                        f"dwg2dxf conversion failed (exit code {proc.returncode}). "
                        f"This may happen with DWG files from newer AutoCAD/Revit versions "
                        f"that LibreDWG doesn't fully support yet. "
                        f"stderr: {proc.stderr[:300] if proc.stderr else 'no output'}"
                    ),
                    warnings=warnings,
                )

            # ── Check if DXF was actually created ──
            # dwg2dxf may output to the same directory with the same stem
            if not os.path.isfile(dxf_path):
                # Try to find any .dxf file in the temp dir
                dxf_files = list(Path(temp_dir).glob("*.dxf"))
                if dxf_files:
                    dxf_path = str(dxf_files[0])
                else:
                    return ConversionResult(
                        success=False,
                        error=(
                            "dwg2dxf completed but no DXF file was produced. "
                            "The DWG file may be corrupted or in an unsupported format."
                        ),
                        warnings=warnings,
                    )

            # ── Validate the DXF file ──
            dxf_size = os.path.getsize(dxf_path)
            if dxf_size < 100:
                warnings.append(
                    f"Converted DXF file is very small ({dxf_size} bytes) — "
                    "the conversion may have produced incomplete output."
                )

            return ConversionResult(
                success=True,
                dxf_path=dxf_path,
                warnings=warnings,
            )

        except subprocess.TimeoutExpired:
            return ConversionResult(
                success=False,
                error=(
                    "dwg2dxf conversion timed out after 120 seconds. "
                    "The DWG file may be too complex or corrupted."
                ),
                warnings=warnings,
            )

        except FileNotFoundError:
            return ConversionResult(
                success=False,
                error=(
                    "dwg2dxf executable was found but could not be run. "
                    "Please verify your LibreDWG installation."
                ),
                warnings=warnings,
            )

    except Exception as e:
        return ConversionResult(
            success=False,
            error=f"DWG conversion error: {str(e)}",
            warnings=warnings,
        )


def cleanup_temp_dir(dxf_path: str):
    """Clean up the temporary directory created during conversion."""
    try:
        temp_dir = os.path.dirname(dxf_path)
        if temp_dir and "firerulx_dwg_" in temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass
