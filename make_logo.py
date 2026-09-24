"""Draw the app logo procedurally. Run with: uv run python make_logo.py

The logo is a contact card on a rounded tile: binder rings on the spine, an avatar and two text
lines. Everything is drawn at a multiple of the target size and scaled down, which is what gives
the edges their antialiasing.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS_DIR: Path = Path(__file__).parent / "assets"
SIZES: tuple[int, ...] = (512, 128)
SUPERSAMPLE: int = 4

TILE_TOP: tuple[int, int, int] = (79, 70, 229)
TILE_BOTTOM: tuple[int, int, int] = (147, 51, 234)
CARD: tuple[int, int, int] = (255, 255, 255)
INK: tuple[int, int, int] = (30, 27, 75)
MUTED: tuple[int, int, int] = (199, 195, 237)
RING: tuple[int, int, int] = (250, 204, 21)


def vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Return a square image shading from `top` to `bottom`."""
    gradient: Image.Image = Image.new("RGB", (1, size))
    pixels = gradient.load()
    if pixels is None:
        raise RuntimeError("Pillow returned an image without pixel access.")
    for y in range(size):
        weight: float = y / (size - 1)
        pixels[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * weight) for i in range(3))
    return gradient.resize((size, size), Image.Resampling.NEAREST)


def draw_logo(size: int) -> Image.Image:
    """Draw the logo at `size` pixels a side."""
    canvas: Image.Image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile_mask: Image.Image = Image.new("L", (size, size), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * 0.22), fill=255
    )
    canvas.paste(vertical_gradient(size, TILE_TOP, TILE_BOTTOM), (0, 0), tile_mask)
    draw: ImageDraw.ImageDraw = ImageDraw.Draw(canvas)

    card_left: float = size * 0.26
    card_right: float = size * 0.80
    card_top: float = size * 0.17
    card_bottom: float = size * 0.83
    draw.rounded_rectangle(
        (card_left, card_top, card_right, card_bottom), radius=size * 0.07, fill=CARD
    )

    # Binder rings over the spine of the card.
    ring_width: float = size * 0.035
    for position in (0.32, 0.5, 0.68):
        centre_y: float = card_top + (card_bottom - card_top) * position
        draw.rounded_rectangle(
            (size * 0.17, centre_y - ring_width, card_left + size * 0.05, centre_y + ring_width),
            radius=ring_width,
            fill=RING,
        )

    head_radius: float = size * 0.072
    head_centre: tuple[float, float] = (size * 0.45, size * 0.38)
    draw.ellipse(
        (
            head_centre[0] - head_radius,
            head_centre[1] - head_radius,
            head_centre[0] + head_radius,
            head_centre[1] + head_radius,
        ),
        fill=INK,
    )
    # Shoulders: a rounded rectangle that meets the head, so the two read as one bust.
    draw.rounded_rectangle(
        (size * 0.345, size * 0.465, size * 0.555, size * 0.65), radius=size * 0.09, fill=INK
    )

    line_left: float = size * 0.58
    line_right: float = size * 0.73
    for centre_y, right in ((size * 0.44, line_right), (size * 0.53, line_right - size * 0.05)):
        draw.rounded_rectangle(
            (line_left, centre_y - size * 0.018, right, centre_y + size * 0.018),
            radius=size * 0.018,
            fill=MUTED,
        )
    return canvas


def render_logo(size: int) -> Image.Image:
    """Draw the logo supersampled and scale it down to `size`."""
    return draw_logo(size * SUPERSAMPLE).resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ASSETS_DIR.mkdir(exist_ok=True)
    for size in SIZES:
        path: Path = ASSETS_DIR / f"logo-{size}.png"
        render_logo(size).save(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
