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

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    exe_name = "矩量拓客-地区视频批量生成"

    version_file = os.path.join(app_dir, "version_info.txt")

    opts = [
        os.path.join(app_dir, "main.py"),
        f"--name={exe_name}",
        "--onefile",
        "--windowed",
        "--noconsole",
        "--clean",
        f"--icon={icon_path}",
        f"--distpath={desktop}",
        f"--version-file={version_file}",
        "--add-data", f"assets{os.pathsep}assets",
        "--add-data", f"config{os.pathsep}config",
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=edge_tts",
        "--hidden-import=piper",
        "--hidden-import=cryptography",
        "--hidden-import=sklearn.cluster",
        "--hidden-import=sklearn.utils._typedefs",
        "--hidden-import=skimage.morphology",
        "--hidden-import=cv2",
        "--collect-all", "cryptography",
        "--collect-all", "sklearn",
        "--collect-all", "skimage",
    ]

    PyInstaller.__main__.run(opts)

    # Copy ffmpeg tools to desktop
    tools_src = os.path.join(app_dir, "tools", "ffmpeg")
    tools_dst = os.path.join(desktop, "tools", "ffmpeg")
    if os.path.isdir(tools_src):
        os.makedirs(tools_dst, exist_ok=True)
        for f in os.listdir(tools_src):
            shutil.copy2(os.path.join(tools_src, f), os.path.join(tools_dst, f))
        print(f"FFmpeg tools copied to: {tools_dst}")

    output = os.path.join(desktop, f"{exe_name}.exe")
    size_mb = os.path.getsize(output) / (1024*1024) if os.path.isfile(output) else 0
    print(f"\nBuild complete! Output: {output} ({size_mb:.0f} MB)")
    print(f"请将 tools/ffmpeg 文件夹放在 EXE 同目录下")


if __name__ == "__main__":
    build()
