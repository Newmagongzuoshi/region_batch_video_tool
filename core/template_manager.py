import json
import os
from models.template_model import TemplateModel
from utils.path_utils import resolve_path, resolve_data_path
from utils.logger import get_logger

logger = get_logger()


class TemplateManager:
    def __init__(self):
        self._built_in: list[TemplateModel] = []
        self._custom: list[TemplateModel] = []
        self._load_built_in()
        self._load_custom()

    def _load_built_in(self):
        path = resolve_path("assets", "templates", "built_in_templates.json")
        if not os.path.isfile(path):
            logger.warning(f"Built-in templates not found: {path}")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("templates", []):
                tmpl = TemplateModel(
                    template_id=item["template_id"],
                    template_name=item["template_name"],
                    category=item["category"],
                    style=item,
                    built_in=True,
                )
                self._built_in.append(tmpl)
            logger.info(f"Loaded {len(self._built_in)} built-in templates")
        except Exception as e:
            logger.error(f"Failed to load built-in templates: {e}")

    def _custom_path(self) -> str:
        return resolve_data_path("config", "custom_templates.json")

    def _load_custom(self):
        path = self._custom_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("templates", []):
                tmpl = TemplateModel(
                    template_id=item["template_id"],
                    template_name=item["template_name"],
                    category=item.get("category", "自定义"),
                    style=item,
                    built_in=False,
                )
                self._custom.append(tmpl)
            logger.info(f"Loaded {len(self._custom)} custom templates")
        except Exception as e:
            logger.error(f"Failed to load custom templates: {e}")

    def _save_custom(self):
        path = self._custom_path()
        data = {
            "templates": [
                {**t.style, "template_id": t.template_id,
                 "template_name": t.template_name, "category": t.category}
                for t in self._custom
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_all_templates(self) -> list[TemplateModel]:
        return self._built_in + self._custom

    def get_by_category(self, category: str) -> list[TemplateModel]:
        return [t for t in self.get_all_templates() if t.category == category]

    def get_categories(self) -> list[str]:
        cats = set()
        for t in self.get_all_templates():
            cats.add(t.category)
        return sorted(cats)

    def get_template(self, template_id: str) -> TemplateModel | None:
        for t in self.get_all_templates():
            if t.template_id == template_id:
                return t
        return None

    def save_custom_template(self, template_id: str, template_name: str,
                             category: str, style: dict) -> bool:
        style["template_id"] = template_id
        style["template_name"] = template_name
        style["category"] = category

        # Remove existing with same ID
        self._custom = [t for t in self._custom if t.template_id != template_id]

        tmpl = TemplateModel(
            template_id=template_id,
            template_name=template_name,
            category=category,
            style=style,
            built_in=False,
        )
        self._custom.append(tmpl)
        self._save_custom()
        return True

    def add_session_template(self, template_id: str, template_name: str,
                             category: str, style: dict) -> bool:
        """Add a session-only template that is NOT persisted to disk."""
        style["template_id"] = template_id
        style["template_name"] = template_name
        style["category"] = category

        # Remove existing session templates with same ID
        self._custom = [t for t in self._custom if t.template_id != template_id]

        tmpl = TemplateModel(
            template_id=template_id,
            template_name=template_name,
            category=category,
            style=style,
            built_in=False,
        )
        self._custom.append(tmpl)
        return True

    def delete_custom_template(self, template_id: str) -> bool:
        before = len(self._custom)
        self._custom = [t for t in self._custom if t.template_id != template_id]
        if len(self._custom) < before:
            self._save_custom()
            return True
        return False

    def export_template(self, template_id: str, path: str) -> bool:
        tmpl = self.get_template(template_id)
        if tmpl is None:
            return False
        with open(path, "w", encoding="utf-8") as f:
            json.dump(tmpl.style, f, ensure_ascii=False, indent=2)
        return True

    def import_template(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            tid = data.get("template_id", os.path.splitext(os.path.basename(path))[0])
            name = data.get("template_name", tid)
            cat = data.get("category", "导入模板")
            self.save_custom_template(tid, name, cat, data)
            return True
        except Exception as e:
            logger.error(f"Import template failed: {e}")
            return False
