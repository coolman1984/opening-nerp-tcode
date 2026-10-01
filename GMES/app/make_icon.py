"""Draw app/assets/samir.ico (needs Pillow; only run when the icon should change)."""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "gmes.ico")


def draw(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = max(2, size // 5)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=(37, 99, 235, 255))
    d.polygon([(size - 1, size // 3), (size - 1, size - 1 - r // 2), (size // 3, size - 1)],
              fill=(59, 130, 246, 255))
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, outline=(29, 78, 216, 255),
                        width=max(1, size // 32))
    try:
        font = ImageFont.truetype("segoeuib.ttf", int(size * 0.62))
    except OSError:
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), "G", font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), "G", font=font, fill="white")
    return img


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw(256).save(OUT, sizes=[(s, s) for s in sizes])
    print("wrote", OUT)
