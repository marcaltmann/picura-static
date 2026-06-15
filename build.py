from pathlib import Path

from PIL import Image

# Map a site.yaml format name to its Pillow save format and the file
# extension used in output filenames (which templates reference verbatim,
# e.g. ``{{ photo.stem }}-display.jpeg``).
_FORMATS = {
    'jpeg': ('JPEG', 'jpeg'),
    'webp': ('WEBP', 'webp'),
    'avif': ('AVIF', 'avif'),
}


def _resize_to_width(img, target_width):
    # Never upscale: Darktable already exports the display size, so a source
    # narrower than the target is used as-is.
    if img.width <= target_width:
        return img.copy()
    height = round(img.height * target_width / img.width)
    return img.resize((target_width, height), Image.LANCZOS)


def fan_out(src, out_dir, images_config):
    """Generate resized derivatives of ``src`` in every configured format.

    ``images_config`` is the ``images:`` block from site.yaml: a ``formats``
    list plus one entry per size (``thumb``, ``display``, ...), each with a
    ``width`` and ``quality``. Returns a mapping of size name to its pixel
    dimensions and the per-format output filenames, ready for templating.
    """
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = images_config['formats']
    sizes = {k: v for k, v in images_config.items() if k != 'formats'}

    variants = {}
    with Image.open(src) as img:
        img.load()
        base = img.convert('RGB')
        # Preserve the embedded ICC profile (Darktable writes sRGB) so the
        # derivatives stay color-managed.
        icc = img.info.get('icc_profile')

        for size_name, spec in sizes.items():
            resized = _resize_to_width(base, spec['width'])
            sources = {}
            for fmt in formats:
                pil_format, ext = _FORMATS[fmt]
                filename = f'{src.stem}-{size_name}.{ext}'
                save_kwargs = {'quality': spec['quality']}
                if icc:
                    save_kwargs['icc_profile'] = icc
                resized.save(out_dir / filename, pil_format, **save_kwargs)
                sources[fmt] = filename
            variants[size_name] = {
                'width': resized.width,
                'height': resized.height,
                'sources': sources,
            }
    return variants
