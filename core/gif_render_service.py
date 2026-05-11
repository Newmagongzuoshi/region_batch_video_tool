import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

from core.gif_frame_decoder import GifFrameDecoder
from core.text_render_service import TextRenderService
from core.cache_manager import CacheManager
from models.text_layer_model import TextLayerModel
from models.region_model import RegionModel
from utils.logger import get_logger

logger = get_logger()


class GifRenderService:
    def __init__(self, decoder: GifFrameDecoder | None = None):
        self._decoder = decoder
        self._text_renderer = TextRenderService()
        self._cache_mgr = CacheManager()

    def set_decoder(self, decoder: GifFrameDecoder):
        self._decoder = decoder

    def render_one(
        self,
        region_name: str,
        safe_filename: str,
        text_layer: TextLayerModel,
        output_gif_path: str,
        output_png_sequence_dir: str = "",
        skip_png: bool = True,
    ) -> bool:
        if self._decoder is None:
            logger.error("GifFrameDecoder not set")
            return False

        try:
            # Replace {地区} placeholder
            text = text_layer.text_template.replace("{地区}", region_name)

            # Render text image once (text position is same across all frames)
            text_img = self._text_renderer.render_text(text, text_layer)
            if text_img is None:
                logger.error(f"Failed to render text for: {region_name}")
                return False

            # Recalculate X based on actual text width so centering adapts to
            # different region-name lengths. Y is preserved from user's setting.
            if text_layer.center_horizontal:
                gif_w = self._decoder.get_size()[0]
                text_x = int((gif_w - text_img.width) / 2)
                text_pos = (max(0, text_x), int(text_layer.y))
            else:
                text_pos = (int(text_layer.x), int(text_layer.y))

            total_frames = self._decoder.get_frame_count()
            durations = self._decoder.get_durations()

            frames = []
            if not skip_png and output_png_sequence_dir:
                os.makedirs(output_png_sequence_dir, exist_ok=True)

            for i in range(total_frames):
                frame = self._decoder.get_frame(i)
                if frame is None:
                    logger.error(f"Failed to get frame {i} for: {region_name}")
                    return False

                # get_frame() now returns a fresh Image every time — no copy needed
                frame.paste(text_img, text_pos, text_img)

                if not skip_png and output_png_sequence_dir:
                    png_path = os.path.join(output_png_sequence_dir, f"frame_{i+1:05d}.png")
                    frame.save(png_path, "PNG")

                frames.append(frame)

            # Verify frames are not all identical (diagnostic for intermittent bug)
            if total_frames >= 2:
                h0 = hashlib.md5(frames[0].tobytes()).hexdigest()
                h1 = hashlib.md5(frames[1].tobytes()).hexdigest()
                if h0 == h1:
                    h_last = hashlib.md5(frames[-1].tobytes()).hexdigest()
                    logger.warning(
                        f"All rendered GIF frames appear identical for '{region_name}' "
                        f"(frames={total_frames}, hash={h0[:12]}...). "
                        f"Source GIF may have identical frames."
                    )
                else:
                    logger.debug(
                        f"Frame uniqueness OK for '{region_name}': "
                        f"f0={h0[:12]}... f1={h1[:12]}..."
                    )

            # Save GIF
            os.makedirs(os.path.dirname(output_gif_path), exist_ok=True)
            if len(frames) == 1:
                frames[0].save(output_gif_path, "GIF", save_all=True, loop=0)
            else:
                frames[0].save(
                    output_gif_path,
                    "GIF",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=0,
                    optimize=False,
                    disposal=2,
                )

            logger.info(f"Rendered GIF: {output_gif_path} ({total_frames} frames)")
            return True

        except Exception as e:
            logger.error(f"render_one failed for {region_name}: {e}")
            return False

    def render_batch(
        self,
        regions: list[RegionModel],
        text_layer: TextLayerModel,
        output_gif_dir: str,
        max_workers: int = 2,
    ) -> dict:
        if self._decoder is None:
            logger.error("GifFrameDecoder not set")
            return {"success": 0, "failed": len(regions), "results": []}

        results = []
        success_count = 0
        failed_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for region in regions:
                gif_path = os.path.join(output_gif_dir, f"{region.safe_filename}.gif")
                png_dir = self._cache_mgr.ensure_render_dir(region.safe_filename)
                future = executor.submit(
                    self.render_one,
                    region.clean_name,
                    region.safe_filename,
                    text_layer,
                    gif_path,
                    png_dir,
                )
                futures[future] = region

            for future in as_completed(futures):
                region = futures[future]
                try:
                    ok = future.result()
                    if ok:
                        success_count += 1
                        results.append({"region": region.clean_name, "status": "completed"})
                    else:
                        failed_count += 1
                        results.append({"region": region.clean_name, "status": "failed"})
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Batch GIF render exception for {region.clean_name}: {e}")
                    results.append({"region": region.clean_name, "status": "failed", "error": str(e)})

        logger.info(f"Batch GIF render done: {success_count} ok, {failed_count} failed")
        return {"success": success_count, "failed": failed_count, "results": results}
