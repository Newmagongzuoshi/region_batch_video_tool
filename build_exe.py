"""
PyInstaller build script for 矩量拓客：地区视频批量生成

Usage:
    pip install pyinstaller
    python build_exe.py

Output: 矩量拓客-地区视频批量生成.exe
"""
import os
import sys
import shutil

import PyInstaller.__main__


def build():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(app_dir, "assets", "icon.ico")

    for d in ["build", "dist"]:
        path = os.path.join(app_dir, d)
        if os.path.isdir(path):
            shutil.rmtree(path)

    opts = [
        os.path.join(app_dir, "main.py"),
        "--name=矩量拓客-地区视频批量生成",
        "--onefile",
        "--windowed",
        "--noconsole",
        "--clean",
        f"--icon={icon_path}",
        "--add-data", f"assets{os.pathsep}assets",
        "--add-data", f"config{os.pathsep}config",
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=edge_tts",
        "--hidden-import=piper",
        "--hidden-import=cryptography.hazmat.backends",
        "--hidden-import=cryptography.hazmat.primitives",
        "--collect-all", "cryptography",
    ]

    PyInstaller.__main__.run(opts)

    print("\nBuild complete!")
    output = os.path.join(app_dir, "dist", "矩量拓客-地区视频批量生成.exe")
    print(f"Output: {output}")


if __name__ == "__main__":
    build()
