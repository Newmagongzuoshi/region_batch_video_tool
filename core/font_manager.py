"""Font manager: scan system fonts + built-in fonts, provide advanced font
lists with grouping, search, recent tracking, and fallback chain."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from utils.path_utils import resolve_path, resolve_data_path
from utils.logger import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# FontInfo
# ---------------------------------------------------------------------------


@dataclass
class FontInfo:
    family: str
    path: str | None = None       # full path to font file, or None if not available
    installed: bool = False        # True = system-installed or built-in
    built_in: bool = False         # True = shipped with the app
    category: str = "系统字体"
    preview_text: str = ""

    @property
    def display_name(self) -> str:
        if self.installed:
            return self.family + (" [内置]" if self.built_in else "")
        return self.family + " [未安装]"


# ---------------------------------------------------------------------------
# Font categories (names only — no font files embedded)
# ---------------------------------------------------------------------------

_ADVANCED_BLACK_FONTS = [
    ("Microsoft YaHei", "微软雅黑"),
    ("Microsoft YaHei UI", "微软雅黑 UI"),
    ("SimHei", "黑体"),
    ("SourceHanSansSC-Regular", "思源黑体"),
    ("SourceHanSansSC-Bold", "思源黑体 Bold"),
    ("SourceHanSansSC-Heavy", "思源黑体 Heavy"),
    ("LXGWWenKai-Regular", "霞鹜文楷"),
    ("NotoSansSC-Regular", "Noto 思源黑体 SC"),
    ("PingFang SC", "苹方"),
    ("HarmonyOS Sans", "鸿蒙字体"),
    ("OPPO Sans", "OPPO 字体"),
    ("Alibaba PuHuiTi", "阿里巴巴普惠体"),
    ("MiSans", "小米 MiSans"),
]

_BUSINESS_TITLE_FONTS = [
    ("SourceHanSansSC-Bold", "思源黑体 Bold"),
    ("SourceHanSansSC-Heavy", "思源黑体 Heavy"),
    ("LXGWWenKai-Regular", "霞鹜文楷"),
    ("Alibaba PuHuiTi 2.0", "阿里巴巴普惠体 2.0"),
    ("HarmonyOS Sans Medium", "鸿蒙字体 Medium"),
    ("HarmonyOS Sans Bold", "鸿蒙字体 Bold"),
]

_PREMIUM_SERIF_FONTS = [
    ("LXGWWenKai-Regular", "霞鹜文楷"),
    ("SimSun", "宋体"),
    ("NSimSun", "新宋体"),
    ("FangSong", "仿宋"),
    ("KaiTi", "楷体"),
    ("STSong", "华文宋体"),
    ("STKaiti", "华文楷体"),
    ("STFangsong", "华文仿宋"),
]

_SHORT_VIDEO_TITLE_FONTS = [
    ("Microsoft YaHei", "微软雅黑 Bold"),
    ("SimHei", "黑体"),
    ("SourceHanSansSC-Heavy", "思源黑体 Heavy"),
    ("SourceHanSansSC-Bold", "思源黑体 Bold"),
    ("Alibaba PuHuiTi Heavy", "阿里巴巴普惠体 Heavy"),
    ("HarmonyOS Sans Bold", "鸿蒙字体 Bold"),
]

_TECH_FONTS = [
    ("HarmonyOS Sans", "鸿蒙字体"),
    ("MiSans", "小米 MiSans"),
    ("OPPO Sans", "OPPO 字体"),
    ("Noto Sans", "Noto Sans"),
    ("Inter", "Inter"),
    ("Roboto", "Roboto"),
    ("Segoe UI", "Segoe UI"),
    ("DIN Alternate", "DIN Alternate"),
    ("Bahnschrift", "Bahnschrift"),
    ("Arial", "Arial"),
    ("Helvetica", "Helvetica"),
]

_MINIMAL_EN_FONTS = [
    ("Inter", "Inter"),
    ("Roboto", "Roboto"),
    ("Helvetica", "Helvetica"),
    ("Arial", "Arial"),
    ("Segoe UI", "Segoe UI"),
    ("SF Pro Display", "SF Pro Display"),
    ("Montserrat", "Montserrat"),
    ("Poppins", "Poppins"),
    ("Futura", "Futura"),
    ("Avenir", "Avenir"),
    ("DIN", "DIN"),
]

# All special font groups (name → display name)
_ALL_GROUPS: dict[str, list[tuple[str, str]]] = {
    "推荐字体": [
        ("Microsoft YaHei", "微软雅黑"),
        ("SimHei", "黑体"),
        ("SourceHanSansSC-Bold", "思源黑体 Bold"),
        ("SourceHanSansSC-Regular", "思源黑体"),
        ("LXGWWenKai-Regular", "霞鹜文楷"),
        ("NotoSansSC-Regular", "Noto 黑体 SC"),
    ],
    "中文高级黑体": _ADVANCED_BLACK_FONTS,
    "商务标题字体": _BUSINESS_TITLE_FONTS,
    "短视频标题字体": _SHORT_VIDEO_TITLE_FONTS,
    "品牌宋体字体": _PREMIUM_SERIF_FONTS,
    "科技英文字体": _TECH_FONTS,
    "极简英文字体": _MINIMAL_EN_FONTS,
}

# Deduplicated set of all known font family names
_ALL_KNOWN_FAMILIES: set[str] = set()
for _glist in _ALL_GROUPS.values():
    for _name, _display in _glist:
        _ALL_KNOWN_FAMILIES.add(_name)

# ---------------------------------------------------------------------------
# FontManager
# ---------------------------------------------------------------------------


class FontManager:
    def __init__(self):
        self._system_fonts: dict[str, str] = {}  # family → path (system-installed)
        self._builtin_fonts: dict[str, str] = {}  # family → path (bundled with app)
        self._scan_system()
        self._scan_builtin()
        self._recent: list[str] = []
        self._load_recent()

    # ---- scan ----

    def _scan_system(self):
        font_dir = "C:/Windows/Fonts"
        if not os.path.isdir(font_dir):
            logger.warning(f"System font directory not found: {font_dir}")
            return
        try:
            for f in os.listdir(font_dir):
                lower = f.lower()
                if lower.endswith((".ttf", ".ttc", ".otf")):
                    name = os.path.splitext(f)[0]
                    path = os.path.join(font_dir, f)
                    self._system_fonts[name] = path
                    self._add_aliases(name, path)
        except Exception as e:
            logger.error(f"Font scan error: {e}")

    def _scan_builtin(self):
        """Scan bundled fonts in assets/fonts/."""
        builtin_dir = resolve_path("assets", "fonts")
        if not os.path.isdir(builtin_dir):
            return
        try:
            for f in os.listdir(builtin_dir):
                lower = f.lower()
                if lower.endswith((".ttf", ".ttc", ".otf")):
                    name = os.path.splitext(f)[0]
                    path = os.path.join(builtin_dir, f)
                    self._builtin_fonts[name] = path
                    logger.debug(f"Built-in font: {name}")
            if self._builtin_fonts:
                logger.info(f"Loaded {len(self._builtin_fonts)} built-in fonts")
        except Exception as e:
            logger.error(f"Built-in font scan error: {e}")

    def _add_aliases(self, name: str, path: str):
        """Add common font aliases."""
        aliases_map: dict[str, list[str]] = {
            "msyh": ["Microsoft YaHei", "微软雅黑"],
            "msyhbd": ["Microsoft YaHei Bold"],
            "msyhl": ["Microsoft YaHei Light"],
            "simhei": ["SimHei", "黑体"],
            "simsun": ["SimSun", "宋体"],
            "simkai": ["KaiTi", "楷体"],
            "simfang": ["FangSong", "仿宋"],
            "arial": ["Arial"],
            "segoeui": ["Segoe UI"],
            "segui": ["Segoe UI"],
            "calibri": ["Calibri"],
            "times": ["Times New Roman"],
            "cour": ["Courier New"],
            "tahoma": ["Tahoma"],
            "verdana": ["Verdana"],
            "impact": ["Impact"],
            "georgia": ["Georgia"],
            "comic": ["Comic Sans MS"],
            "bahnschrift": ["Bahnschrift"],
            "roboto": ["Roboto"],
            "inter": ["Inter"],
            "helvetica": ["Helvetica"],
        }
        name_lower = name.lower()
        if name_lower in aliases_map:
            for alias in aliases_map[name_lower]:
                if alias not in self._system_fonts:
                    self._system_fonts[alias] = path

    # ---- query ----

    def get_system_families(self) -> list[str]:
        return sorted(self._system_fonts.keys())

    def get_font_path(self, family: str) -> str | None:
        """Return the full path to a font file, or None if not installed."""
        return self._system_fonts.get(family)

    def is_installed(self, family: str) -> bool:
        return family in self._system_fonts or family in self._builtin_fonts

    # ---- query ----

    def get_font_path(self, family: str) -> str | None:
        """Return full path to font file (system or built-in), or None."""
        return self._system_fonts.get(family) or self._builtin_fonts.get(family)

    def is_builtin(self, family: str) -> bool:
        return family in self._builtin_fonts and family not in self._system_fonts

    # ---- fallback ----

    FALLBACK_CHAIN = [
        "Microsoft YaHei", "SimHei", "PingFang SC",
        "Noto Sans CJK SC", "Source Han Sans SC", "Arial",
    ]

    def get_fallback(self, family: str) -> str:
        """Return the first available font in the fallback chain."""
        if self.is_installed(family):
            return family
        for fb in self.FALLBACK_CHAIN:
            if self.is_installed(fb):
                return fb
        all_fonts = {**self._builtin_fonts, **self._system_fonts}
        if all_fonts:
            return next(iter(all_fonts))
        return "Arial"

    def get_effective_font(self, family: str) -> tuple[str, str | None]:
        """Return (effective_family, font_path) — always succeeds."""
        path = self.get_font_path(family)
        if path:
            return family, path
        fb = self.get_fallback(family)
        return fb, self.get_font_path(fb)

    # ---- groups ----

    def get_groups(self) -> dict[str, list[FontInfo]]:
        """Return all font groups with installation status."""
        result: dict[str, list[FontInfo]] = {}

        # Recent
        recent = self.get_recent()
        if recent:
            result["最近使用"] = recent

        # Named groups
        for group_name, font_list in _ALL_GROUPS.items():
            infos: list[FontInfo] = []
            for family, display in font_list:
                installed = self.is_installed(family)
                built_in = self.is_builtin(family)
                infos.append(FontInfo(
                    family=family,
                    path=self.get_font_path(family),
                    installed=installed,
                    built_in=built_in,
                    category=group_name,
                    preview_text=display if not installed else family,
                ))
            result[group_name] = infos

        # System fonts (only those not already in special groups)
        sys_infos: list[FontInfo] = []
        for family, path in sorted(self._system_fonts.items()):
            if family not in _ALL_KNOWN_FAMILIES:
                sys_infos.append(FontInfo(
                    family=family, path=path, installed=True,
                    category="系统字体", preview_text=family,
                ))
        if sys_infos:
            result["系统字体"] = sys_infos

        return result

    def search(self, query: str) -> list[FontInfo]:
        """Search fonts by name (Chinese/English, fuzzy)."""
        q = query.lower().strip()
        if not q:
            return []
        results: list[FontInfo] = []
        seen: set[str] = set()

        # Search system fonts
        for family, path in sorted(self._system_fonts.items()):
            if q in family.lower() and family not in seen:
                seen.add(family)
                results.append(FontInfo(family=family, path=path, installed=True,
                                        category="搜索结果", preview_text=family))

        # Search known fonts (not installed)
        for family in _ALL_KNOWN_FAMILIES:
            if q in family.lower() and family not in seen:
                seen.add(family)
                results.append(FontInfo(family=family, installed=False,
                                        category="搜索结果"))

        return results

    # ---- recent ----

    def _recent_path(self) -> str:
        return resolve_data_path("config", "recent_fonts.json")

    def _load_recent(self):
        path = self._recent_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = data.get("recent", [])
            # Filter to installed fonts
            self._recent = [f for f in loaded if self.is_installed(f)]
        except Exception:
            self._recent = []

    def _save_recent(self):
        path = self._recent_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"recent": self._recent}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save recent fonts: {e}")

    def mark_used(self, family: str):
        """Mark a font as recently used. Moves to front, max 8."""
        if family in self._recent:
            self._recent.remove(family)
        self._recent.insert(0, family)
        if len(self._recent) > 8:
            self._recent = self._recent[:8]
        self._save_recent()

    def get_recent(self) -> list[FontInfo]:
        return [FontInfo(family=f, path=self._system_fonts.get(f),
                        installed=True, category="最近使用", preview_text=f)
                for f in self._recent if self.is_installed(f)]


# ---- singleton ----

_font_manager: FontManager | None = None


def get_font_manager() -> FontManager:
    global _font_manager
    if _font_manager is None:
        _font_manager = FontManager()
    return _font_manager
