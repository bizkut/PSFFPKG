#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import argparse
import tempfile
import shutil
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"

def _resolve_tool():
    """Locate UFS2Tool and determine how to launch it.

    Resolution order (all paths checked next to the script first, then PATH):
    1. UFS2TOOL_PATH environment variable (points to exe, dll, or native binary)
    2. Native binary  : UFS2Tool
    3. .NET DLL       : UFS2Tool.dll  (requires 'dotnet' in PATH)
    4. Windows binary : UFS2Tool.exe  (requires 'wine' on non-Windows)

    Returns a list that can be passed directly to subprocess (e.g. [tool_path]
    or ["wine", tool_path] or ["dotnet", dll_path]).
    """
    script_dir = Path(__file__).parent

    # Helper: check next to script, then PATH
    def _find(name):
        local = script_dir / name
        if local.is_file():
            return str(local)
        found = shutil.which(name)
        if found:
            return found
        return None

    # 1. Explicit override from environment
    env_path = os.environ.get("UFS2TOOL_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            if env_path.endswith(".dll") and shutil.which("dotnet"):
                return ["dotnet", str(p)]
            if not IS_WINDOWS and env_path.endswith(".exe"):
                wine = shutil.which("wine")
                if wine:
                    return [wine, str(p)]
            return [str(p)]

    # 2. Native binary (Unix or Windows)
    native = _find("UFS2Tool")
    if native:
        return [native]

    # 3. .NET DLL (requires dotnet CLI)
    dotnet = shutil.which("dotnet")
    if dotnet:
        dll = _find("UFS2Tool.dll")
        if dll:
            return [dotnet, dll]

    # 4. Windows .exe  — native on Windows, Wine fallback on Unix
    exe = _find("UFS2Tool.exe")
    if exe:
        if not IS_WINDOWS:
            wine = shutil.which("wine")
            if wine:
                return [wine, exe]
        return [exe]

    raise FileNotFoundError(
        "UFS2Tool not found. Options:\n"
        "  • Place a native 'UFS2Tool' binary next to the script or in PATH\n"
        "  • Place 'UFS2Tool.dll' next to the script and install .NET 8+ SDK\n"
        "  • Place 'UFS2Tool.exe' next to the script (Wine required on macOS/Linux)\n"
        "  • Set UFS2TOOL_PATH to the full path of the tool."
    )


def calculate_directory_size_bytes(path):
    """Calculate the actual size of a directory in bytes (sum of all file sizes)"""
    total = 0
    for entry in Path(path).rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def run_newfs_with_D(tool_cmd, input_dir, output_image):
    """
    Run command:
    UFS2Tool newfs -O 2 -b 32768 -f 4096 -D <input_dir> <output_image>
    Shows live output from the tool.
    """
    cmd = tool_cmd + [
        "newfs",
        "-O", "2",
        "-b", "32768",
        "-f", "4096",
        "-D", input_dir,
        output_image
    ]
    print(f"[INFO] Executing command: {' '.join(cmd)}")
    print("[INFO] Creating UFS2 image... (this may take a while)")
    print("-" * 50)

    try:
        # Run the command without capturing output – the tool writes directly to console
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        print("[ERROR] UFS2Tool execution failed.")
        sys.exit(1)

    print("-" * 50)
    print("[INFO] Image creation completed successfully.")
    return output_image

def interactive_input():
    """Get input from user in interactive mode (no command-line arguments)"""
    print("=== Create UFS2 image and convert to ffpkg ===")
    while True:
        in_dir = input("Enter the game dump folder path: ").replace('"','').replace("'",'').strip()
        if not in_dir:
            print("❌ Path cannot be empty.")
            continue
        if not os.path.isdir(in_dir):
            print("❌ Directory is not valid.")
            continue
        break
    out_dir = input("Enter output folder path (default: current directory): ").replace('"','').replace("'",'').strip()
    if not out_dir:
        out_dir = os.getcwd()
    return in_dir, out_dir

def main():
    # Detect execution mode: use argparse if arguments are provided
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(
            description="Create UFS2 image from directory using UFS2Tool and convert to ffpkg"
        )
        parser.add_argument("input_dir", help="Path to the game dump folder")
        parser.add_argument(
            "output_dir", nargs="?", default=os.getcwd(),
            help="Path to output folder (default: current directory)"
        )
        args = parser.parse_args()
        input_dir = args.input_dir
        output_dir = args.output_dir
    else:
        input_dir, output_dir = interactive_input()

    # Validate input directory
    if not os.path.isdir(input_dir):
        print(f"❌ Error: Input directory '{input_dir}' does not exist.")
        sys.exit(1)

    # Create output directory if needed
    os.makedirs(output_dir, exist_ok=True)

    # Output file name based on input folder name
    folder_name = os.path.basename(os.path.normpath(input_dir))
    if not folder_name:
        folder_name = "output"
    final_filename = f"{folder_name}.ffpkg"
    final_path = os.path.join(output_dir, final_filename)

    # Calculate and display directory size and estimated image size
    bytes_size = calculate_directory_size_bytes(input_dir)
    slack = 10 * 1024 * 1024  # 10 MB
    total_bytes = bytes_size + slack
    estimated_mb = (total_bytes + (1024*1024 - 1)) // (1024*1024)
    print(f"[INFO] Actual file size: {bytes_size:,} bytes")
    print(f"[INFO] Estimated image size (with 10 MB slack): about {estimated_mb} MB")
    print(f"[INFO] Final file: {final_path}")

    # Locate the tool
    try:
        tool_cmd = _resolve_tool()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Create a temporary file in the output directory
    temp_file = tempfile.NamedTemporaryFile(
        dir=output_dir, prefix=f"{folder_name}_", suffix=".tmp", delete=False
    )
    temp_path = temp_file.name
    temp_file.close()

    try:
        run_newfs_with_D(tool_cmd, input_dir, temp_path)

        if os.path.exists(final_path):
            os.remove(final_path)
        os.rename(temp_path, final_path)
        print(f"✅ UFS2 image successfully created and renamed to ffpkg:\n   {final_path}")

    except Exception as e:
        print(f"❌ Error during image creation: {e}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        sys.exit(1)

    # On Windows, when launched from Explorer, keep the window open briefly
    # so the user can see the result.  On Unix the user already has a terminal.
    if IS_WINDOWS:
        print("\n[INFO] Window will close automatically in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    main()