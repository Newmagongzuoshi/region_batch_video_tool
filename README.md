# 地区批量视频融合生成软件

根据用户上传的元视频、透明 GIF 和地区列表，批量生成带文字叠加和语音的地区化 MP4 短视频。

## 功能介绍

1. **素材导入** — 导入元视频(MP4)、元GIF动图、地区列表(TXT)，自动检测素材合法性
2. **GIF 编辑** — 可视化拖动文字图层，50 套内置花字模板，支持描边/阴影/渐变/底色
3. **视频预览** — 截取视频首帧，拖动 GIF 叠加层实时预览合成效果，支持缩放定位
4. **语音设置** — 多引擎支持：Edge TTS(免费)、Piper TTS(本地离线)、Windows SAPI5、火山引擎
5. **API Key 管理** — 加密保存第三方 TTS API 密钥，支持火山引擎等 HTTP TTS
6. **批量生成** — 流水线并行处理，一键生成所有地区 MP4，带计时器和实时日志
7. **输出报告** — 自动生成成功/失败清单

## 运行环境

- Windows 10 / Windows 11 64 位
- Python 3.11+
- FFmpeg（ffmpeg.exe + ffprobe.exe）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行软件
python main.py
```

## 使用流程

1. 在「素材导入」页选择元视频、元GIF和地区.txt，点击「检查素材」
2. 在「GIF 编辑」页添加文字并拖动到合适位置，选择花字模板
3. 点击「视频预览」进入预览模式，拖动 GIF 和文字定位到视频上
4. 在「语音设置」页选择 TTS 引擎和音色，点击「试听」
5. 切换到「批量生成」页，点击「开始生成」
6. 查看实时进度和 MP4 生成日志

## 语音引擎

| 引擎 | 说明 | 需要网络 | 需要 Key |
|------|------|----------|----------|
| Edge TTS | 微软免费神经网络，8 种中文音色 | 是 | 否 |
| Piper TTS | 本地离线 AI 引擎，首次自动下载模型 | 否 | 否 |
| Windows SAPI5 | 系统自带语音 | 否 | 否 |
| 火山引擎 | 云端 TTS API，17 种音色 | 是 | 是 |

## FFmpeg 准备

1. 将 ffmpeg.exe 和 ffprobe.exe 放入项目 `tools/ffmpeg/` 目录
2. 或系统已安装 FFmpeg 并加入 PATH

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

输出在 `dist/RegionBatchVideoTool/`

## 项目结构

```
region_batch_video_tool/
├── main.py
├── requirements.txt
├── build_exe.py
├── config/                     # 配置文件
├── assets/templates/           # 50 套花字模板
├── core/                       # 核心业务 (GIF渲染/TTS/视频合成)
├── ui/                         # PySide6 界面
├── models/                     # 数据模型
├── utils/                      # 工具函数
├── tests/                      # 单元测试
├── cache/                      # 临时缓存
├── tools/ffmpeg/               # FFmpeg 可执行文件
└── output/生成的视频/           # 最终输出
```
