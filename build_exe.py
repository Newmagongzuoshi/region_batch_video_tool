"""
PyInstaller build script for Region Batch Video Tool.

Usage:
    pip install pyinstaller
    python build_exe.py

Output: dist/RegionBatchVideoTool/
"""
import os
import sys
import shutil

import PyInstaller.__main__


def build():
    app_dir = os.path.dirname(os.path.abspath(__file__))

    # Clean previous build
    for d in ["build", "dist"]:
        path = os.path.join(app_dir, d)
        if os.path.isdir(path):
            shutil.rmtree(path)

    opts = [
        os.path.join(app_dir, "main.py"),
        "--name=RegionBatchVideoTool",
        "--onedir",
        "--windowed",
        "--noconsole",
        "--clean",
        "--add-data", f"assets{os.pathsep}assets",
        "--add-data", f"config{os.pathsep}config",
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=pyttsx3.drivers",
        "--hidden-import=pyttsx3.drivers.sapi5",
        "--hidden-import=cryptography.hazmat.backends",
        "--hidden-import=cryptography.hazmat.primitives",
        "--collect-all", "pyttsx3",
        "--collect-all", "keyring",
        "--collect-all", "cryptography",
    ]

    PyInstaller.__main__.run(opts)

    print("\nBuild complete!")
    print(f"Output: {os.path.join(app_dir, 'dist', 'RegionBatchVideoTool')}")


if __name__ == "__main__":
    build()
