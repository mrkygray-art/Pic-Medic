"""Draw PC Medic's icon (a white pulse line on a blue rounded square) as a multi-size .ico. Needs Pillow."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (0, 95, 184, 255)  # #005FB8, the app's accent
PULSE = [(3, 12), (7, 12), (10, 5), (14, 19), (17, 12), (21, 12)]  # the same 24x24 path as the page's icon


def draw(size=256):
    scale = size / 24
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=round(6 * scale), fill=ACCENT)
    points = [(x * scale, y * scale) for x, y in PULSE]
    width = max(2, round(2.4 * scale))
    d.line(points, fill='white', width=width, joint='curve')
    for x, y in (points[0], points[-1]):  # round line caps
        r = width / 2
        d.ellipse([x - r, y - r, x + r, y + r], fill='white')
    return img


def main(out):
    big = draw(1024).resize((256, 256), Image.LANCZOS)  # draw large, then shrink, for smooth edges
    big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('Wrote', out)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name('pcmedic.ico')))
