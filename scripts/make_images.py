"""Generate og.png (1200x630), favicon.ico and apple-touch-icon.png. Dev-only (needs Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "app" / "static"
NAVY, NAVY2, AMBER, LIGHT, MUTED = (16, 36, 62), (26, 53, 90), (227, 168, 90), (246, 244, 238), (201, 211, 222)
B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
R = "/System/Library/Fonts/Supplemental/Arial.ttf"


def check_icon(size):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.2), fill=AMBER)
    w = max(2, int(size * 0.11))
    d.line([(size * .26, size * .52), (size * .43, size * .69), (size * .75, size * .33)], fill=NAVY, width=w, joint="curve")
    return im


og = Image.new("RGB", (1200, 630), NAVY)
d = ImageDraw.Draw(og)
d.rectangle([0, 560, 1200, 630], fill=NAVY2)
og.paste(check_icon(96), (80, 72), check_icon(96))
d.text((196, 92), "UAE Invoice Check", font=ImageFont.truetype(B, 44), fill=LIGHT)
d.text((80, 210), "Will your invoices pass", font=ImageFont.truetype(B, 66), fill=LIGHT)
d.text((80, 290), "UAE e-invoicing?", font=ImageFont.truetype(B, 66), fill=AMBER)
d.text((80, 390), "Free check: upload Excel, CSV, PDF or XML. Official PINT AE 1.0.2", font=ImageFont.truetype(R, 30), fill=MUTED)
d.text((80, 432), "rules explained in plain language. Files never stored.", font=ImageFont.truetype(R, 30), fill=MUTED)
d.text((80, 580), "ASP by 31 Mar 2027  ·  Go-live 1 Jul 2027  ·  AED 5,000/month penalty", font=ImageFont.truetype(B, 26), fill=AMBER)
og.save(OUT / "og.png", optimize=True)
check_icon(180).save(OUT / "apple-touch-icon.png")
check_icon(64).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
print("ok", (OUT / "og.png").stat().st_size, (OUT / "favicon.ico").stat().st_size)
