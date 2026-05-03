from dataclasses import dataclass, field


@dataclass
class TemplateModel:
    template_id: str
    template_name: str
    category: str
    style: dict = field(default_factory=dict)
    preview_image: str | None = None
    built_in: bool = True
