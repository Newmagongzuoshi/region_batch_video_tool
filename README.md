# 矩量拓客：地区视频批量生成 v1.6.5

> 导入元视频、透明 GIF 和地区列表，自动提取 GIF 花字颜色，批量生成带文字叠加和语音的地区化短视频。240 个视频约 30 秒。

[![Version](https://img.shields.io/badge/version-1.6.5-blue)](https://github.com/Newmagongzuoshi/region_batch_video_tool)
[![Python](https://img.shields.io/badge/python-3.11+-green)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)]()

## ✨ 项目亮点

- **10 倍性能**：TTS 异步并发 + GPU 硬件编码 + head/tail 分段复用，240 视频 5 分钟 → 30 秒
- **自适应硬件**：自动检测 NVENC/AMF/QSV/Media Foundation，无 GPU 回退 CPU x264
- **100 个花字模板**：5 大类别（爆款促销 / 蓝青科技 / 白字双层描边 / 金属重工 / 渐变流光）
- **5 个内置字体**：思源黑体 Bold/Regular/Heavy、霞鹜文楷、Noto Sans SC，无需系统安装
- **素材检查自动配色**：检测 GIF 花字的填充色和描边色，自动应用到 {地区} 文字

## 📦 快速开始

```bash
pip install -r requirements.txt
python main.py
```

打包 EXE：
```bash
python build_exe.py   # 输出 矩量拓客-地区视频批量生成-v1.6.x.exe 到桌面
```

## 🚀 使用流程

1. **素材导入** → 选元视频 MP4 + 元 GIF + 地区 TXT，点击检查素材
2. **GIF 编辑** → 自动进入视频预览，自动添加 {地区} 文字并匹配花字颜色
3. **选择模板** → 100 个花字样式一键套用，描边/渐变/阴影/双层描边可调
4. **调整位置** → 拖动 GIF 和文字到合适位置，缩放倍数自动匹配视频高度
5. **批量生成** → 一键生成所有地区 MP4，实时进度 + 生成报告

## 🎨 花字模板（100 个)

| 类别 | 数量 | 风格 |
|------|------|------|
| 爆款促销风 | 20 | 红+金、黑边阴影 |
| 蓝青科技风 | 20 | 蓝+青 glow、新闻风 |
| 白字双层描边风 | 20 | 白字芯 + 内外双描边 |
| 金属重工风 | 20 | 黄金+黑描边厚重风格 |
| 渐变流光风 | 20 | 3-stop 渐变，4 方向 |

## 🎤 语音引擎

| 引擎 | 说明 | 网络 | Key |
|------|------|------|-----|
| Edge TTS | 微软免费，24线程并发，8 个中文音色 | 需要 | 否 |
| Piper TTS | 本地离线 AI | 否 | 否 |
| Windows SAPI5 | 系统自带 | 否 | 否 |
| 火山引擎 | 云端 TTS API | 需要 | 是 |

## ⚡ 性能

| 特性 | 说明 |
|------|------|
| 自适应编码器 | NVENC → AMF → QSV → Media Foundation → CPU x264 |
| 自适应并发 | GPU 4-8 workers，CPU 8-24 workers |
| TTS 预生成 | Edge TTS 24 线程并发，3 次失败重试 |
| 分段复用 | head(3s) GPU 编码 + tail GPU 编码缓存复用 |
| 单视频耗时 | ~0.5 秒（102 视频约 50 秒） |

## 🖥️ 系统信息展示

批量生成页面自动检测并显示：
- 电脑配置：CPU 型号、GPU 型号、内存大小
- 生成方案：编码器排名 ①②③④ + 并发数 + 语音引擎

## 📁 项目结构

```
region_batch_video_tool/
├── main.py              # 入口
├── build_exe.py         # 打包脚本
├── version_info.txt     # EXE 版本信息
├── assets/
│   ├── fonts/           # 5 个内置中文字体
│   ├── templates/       # 100 个花字模板 JSON
│   └── icon.ico
├── config/              # 运行配置
├── core/                # 核心引擎
│   ├── batch_task_manager.py   # 异步流水线
│   ├── video_composer.py       # FFmpeg 视频合成
│   ├── text_render_service.py  # PIL 文字渲染
│   ├── gif_render_service.py   # GIF 叠加
│   ├── font_manager.py         # 字体管理(系统+内置)
│   ├── font_style_analyzer.py  # 花字颜色提取
│   └── ffmpeg_service.py       # FFmpeg 编码器检测
├── ui/                  # PySide6 界面
├── models/              # 数据模型
└── tools/ffmpeg/        # FFmpeg 可执行文件
```

## 📊 生成报告示例

```
生成时间: 2026-05-16 12:56:38
总计: 102  成功: 102  失败: 0
========================================

【电脑配置】
  CPU: 12th Gen i5-12400F (12 核)
  GPU: Intel Arc A380 Graphics
  内存: 32 GB

【生成方案】
  编码器: Intel QSV GPU  ③ 较快
  并发数: 8 线程
  视频分段: head(3.0s)+tail 复用
  总耗时: 51 秒  |  平均: 0.5 秒/个
```

## 📝 License

MIT
