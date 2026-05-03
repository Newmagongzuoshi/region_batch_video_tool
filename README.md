# 地区批量 GIF / MP3 / 视频融合生成软件

根据用户上传的元视频、透明 GIF 和地区列表，批量生成地区化短视频。

## 功能介绍

1. **素材导入** — 导入元视频(MP4)、元GIF图片、地区列表(TXT)
2. **GIF编辑** — 可视化拖动文字图层，设置花字样式
3. **花字模板** — 内置50套模板，支持描边、阴影、渐变、底色
4. **语音设置** — Windows本地TTS，支持语速/音量调节
5. **API Key管理** — 加密保存第三方TTS API密钥
6. **批量生成** — 后台线程批量生成GIF、MP3、MP4
7. **任务日志** — 实时查看状态，支持导出CSV和JSON报告

## 运行环境

- Windows 10 / Windows 11 64位
- Python 3.11+
- FFmpeg（需要 ffmpeg.exe 和 ffprobe.exe）

## 安装运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行软件
python main.py
```

## FFmpeg 准备

两种方式：
1. 将 ffmpeg.exe 和 ffprobe.exe 放入 `tools/ffmpeg/` 目录
2. 系统已安装 FFmpeg 并加入 PATH

## 使用流程

1. 打开软件，在「素材导入」页选择元视频、元GIF和地区.txt
2. 在「GIF编辑」页拖动文字到合适位置，选择花字模板
3. 在「语音设置」页选择音色和参数
4. 在「批量生成」页创建并启动任务
5. 在「任务日志」页查看进度和导出报告

## 输出文件

- `output/材料库/` — 每个地区的 GIF 和 MP3
- `output/生成的视频/` — 每个地区的最终 MP4

## 打包 EXE

```bash
pip install pyinstaller
python build_exe.py
```

输出在 `dist/RegionBatchVideoTool/`

## 开发

```bash
# 运行测试
python -m unittest discover tests/ -v

# 项目结构
region_batch_video_tool/
├─ main.py              # 入口
├─ config/              # 配置文件
├─ assets/templates/    # 内置50套花字模板
├─ core/                # 核心业务逻辑
├─ ui/                  # PySide6 界面
├─ models/              # 数据模型
├─ utils/               # 工具函数
├─ tests/               # 单元测试
├─ cache/               # 缓存和SQLite
└─ output/              # 输出目录
```
