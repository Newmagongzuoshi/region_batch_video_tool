# 矩量拓客：地区视频批量生成

导入元视频、透明 GIF 动图和地区列表，批量生成带文字叠加和语音配音的地区化 MP4 短视频。

## 核心功能

1. **素材导入** — 导入元视频(MP4)、元GIF动图、地区列表(TXT)，自动检测素材合法性
2. **GIF 编辑** — 可视化拖动文字图层、50 套剪映风格花字模板（经典/阴影/霓虹/标签/描边）
3. **视频预览** — 截取视频首帧为背景，拖动 GIF 叠加层实时预览合成效果，支持缩放定位
4. **语音设置** — 多引擎：Edge TTS(微软免费)、Piper TTS(本地离线)、Windows SAPI5、火山引擎
5. **批量生成** — 自适应并发流水线，一键生成所有地区 MP4，带实时计时器和生成日志
6. **输出报告** — 自动生成 `AA视频生成报告.txt`，列出成功/失败清单

## 运行环境

- Windows 10 / 11 64 位
- Python 3.11+
- FFmpeg（ffmpeg.exe + ffprobe.exe）

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行软件
python main.py
```

## 使用流程

1. 「素材导入」→ 选择元视频、元GIF、地区.txt，点击「检查素材」
2. 「GIF 编辑」→ 添加文字并拖动定位，选择花字模板，调整描边/阴影/渐变
3. 「视频预览」→ 查看合成效果，拖动 GIF 位置，调整缩放
4. 「语音设置」→ 选择 TTS 引擎和音色，点击「试听」
5. 「批量生成」→ 点击「开始生成」，查看实时进度

## 语音引擎

| 引擎 | 说明 | 网络 | Key |
|------|------|------|-----|
| Edge TTS | 微软免费神经网络，8 个中文音色 | 需要 | 否 |
| Piper TTS | 本地离线 AI，首次自动下载模型 | 否 | 否 |
| Windows SAPI5 | 系统自带语音 | 否 | 否 |
| 火山引擎 | 云端 TTS API，17 个音色 | 需要 | 是 |

## 性能特点

- **自适应并发**：根据 CPU 核心数自动调整管线数（8-48 条）
- **流水线并行**：GIF 渲染、TTS 合成、MP4 编码同时进行
- **FFmpeg ultrafast 预设**：编码速度提升 5-10 倍

## FFmpeg 准备

1. 将 `ffmpeg.exe` 和 `ffprobe.exe` 放入 `tools/ffmpeg/` 目录
2. 或系统已安装 FFmpeg 并加入 PATH 环境变量

## 输出结构

```
output/
└── 生成的视频/
    ├── 温州市.mp4
    ├── 杭州市.mp4
    ├── AA视频生成报告.txt
    └── ...
```

## 打包 EXE

```bash
pip install pyinstaller
python build_exe.py
```

输出 `dist/矩量拓客-地区视频批量生成.exe`

## 项目结构

```
region_batch_video_tool/
├── main.py                     # 入口
├── requirements.txt            # 依赖
├── build_exe.py                # 打包脚本
├── assets/                     # 图标 + 50 套花字模板
├── config/                     # 配置文件
├── core/                       # 核心业务 (GIF渲染/TTS/视频合成/批量管线)
├── ui/                         # PySide6 界面
├── models/                     # 数据模型
├── utils/                      # 工具函数
├── tests/                      # 单元测试
├── cache/                      # 临时缓存
└── output/生成的视频/           # 最终输出
```
