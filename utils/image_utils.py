from PIL import Image


def overlay_text_on_frame(
    frame: Image.Image,
    text_image: Image.Image,
    position: tuple[int, int],
) -> Image.Image:
    """Composite a text image onto a frame at the given position."""
    result = frame.copy()
    result.paste(text_image, position, text_image)
    return result


def create_blank_rgba(width: int, height: int) -> Image.Image:
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def resize_keep_aspect(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    img_ratio = img.width / img.height
    target_ratio = target_width / target_height

    if img_ratio > target_ratio:
        new_w = target_width
        new_h = int(target_width / img_ratio)
    else:
        new_h = target_height
        new_w = int(target_height * img_ratio)

    return img.resize((new_w, new_h), Image.LANCZOS)
