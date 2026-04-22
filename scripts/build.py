import os
import subprocess
import sys
from pathlib import Path


def build():
    print("Building mc-helper standalone binary...")

    root = Path(__file__).parent.parent
    src = root / "src"
    entry_point = src / "mc_helper" / "cli.py"

    if not entry_point.exists():
        print(f"Error: Entry point {entry_point} not found.")
        sys.exit(1)

    # Base PyInstaller command
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "mc-helper",
        # Include data files. format is src:dest
        # On Windows, separator is ;, on Unix it is :
        f"--add-data={src / 'mc_helper' / 'data'}{os.pathsep}{Path('mc_helper') / 'data'}",
        str(entry_point),
    ]

    print(f"Running command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True, cwd=root)
        print("\nSuccess! Binary created in 'dist/mc-helper'")
    except subprocess.CalledProcessError as e:
        print(f"\nError: PyInstaller failed with exit code {e.returncode}")
        sys.exit(e.returncode)


if __name__ == "__main__":
    build()
