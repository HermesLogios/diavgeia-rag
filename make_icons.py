from PIL import Image, ImageDraw, ImageFont

STAMP = (20, 82, 63)
PAPER = (240, 239, 234)
FONT = r"C:\Windows\Fonts\arialbd.ttf"

for size in (192, 512):
    img = Image.new("RGB", (size, size), STAMP)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, int(size * 0.56))
    box = d.textbbox((0, 0), "Δ", font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]),
           "Δ", font=f, fill=PAPER)
    img.save(f"static/icon-{size}.png")
    print(f"static/icon-{size}.png")