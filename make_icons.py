"""앱 아이콘 생성기.
풀블리드(모서리까지 꽉 찬) 초록 그라데이션 위에 흰색 돼지저금통 실루엣 +
하트가 새겨진 동전. 512/192 PNG를 static/ 에 덮어쓴다.

    python make_icons.py
"""
from PIL import Image, ImageDraw, ImageFilter

SS = 4                     # 슈퍼샘플링 배율
U = 1024                   # 논리 좌표계
S = U * SS
WHITE = (255, 255, 255, 255)

TOP = (43, 190, 134)       # --color-primary 계열
BOT = (18, 137, 90)        # --color-action 계열


def px(v):
    return int(round(v * U * SS))


def gradient(size):
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        g.putpixel((0, y), tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)))
    return g.resize((size, size))


def ellipse(d, cx, cy, rx, ry, fill):
    d.ellipse([px(cx - rx), px(cy - ry), px(cx + rx), px(cy + ry)], fill=fill)


def rrect(d, x0, y0, x1, y1, r, fill):
    d.rounded_rectangle([px(x0), px(y0), px(x1), px(y1)], radius=px(r), fill=fill)


def heart(d, cx, cy, w, fill):
    # 두 원 + 삼각형으로 만든 하트 (전체 폭 = w)
    r = w / 4.0
    cyl = cy - r * 0.35                     # 두 원의 중심 y
    d.ellipse([px(cx - 2 * r), px(cyl - r), px(cx), px(cyl + r)], fill=fill)
    d.ellipse([px(cx), px(cyl - r), px(cx + 2 * r), px(cyl + r)], fill=fill)
    d.polygon([
        (px(cx - 2 * r), px(cyl)),
        (px(cx + 2 * r), px(cyl)),
        (px(cx), px(cyl + 2.3 * r)),
    ], fill=fill)


def build():
    bg = gradient(S).convert("RGBA")

    # 부드러운 그림자
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    ellipse(ds, 0.505, 0.60, 0.31, 0.235, (6, 60, 38, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(px(0.022)))

    # 흰색 실루엣
    fg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(fg)
    # 귀
    d.polygon([(px(0.295), px(0.43)), (px(0.355), px(0.315)), (px(0.445), px(0.44))], fill=WHITE)
    # 다리
    for cx in (0.37, 0.65):
        rrect(d, cx - 0.048, 0.72, cx + 0.048, 0.83, 0.038, WHITE)
    # 몸통
    ellipse(d, 0.505, 0.565, 0.305, 0.235, WHITE)
    # 주둥이
    rrect(d, 0.71, 0.50, 0.89, 0.67, 0.065, WHITE)
    # 동전
    ellipse(d, 0.505, 0.215, 0.092, 0.092, WHITE)

    icon = bg.copy()
    icon.alpha_composite(sh)
    icon.alpha_composite(fg)

    # 초록색으로 다시 파내는 부분(배경 그라데이션이 비쳐 보이도록 마스크로 처리)
    cut = Image.new("L", (S, S), 0)
    dc = ImageDraw.Draw(cut)
    rrect(dc, 0.40, 0.365, 0.61, 0.415, 0.03, 255)          # 동전 투입구
    ellipse(dc, 0.60, 0.49, 0.024, 0.024, 255)              # 눈
    ellipse(dc, 0.79, 0.585, 0.019, 0.029, 255)             # 콧구멍
    ellipse(dc, 0.845, 0.585, 0.019, 0.029, 255)
    icon.paste(bg, (0, 0), cut)

    # 동전 속 하트
    hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    heart(ImageDraw.Draw(hl), 0.505, 0.215, 0.10, (255, 255, 255, 255))
    hmask = hl.split()[3]
    icon.paste(bg, (0, 0), hmask)

    icon = icon.convert("RGB")
    for size in (512, 192):
        icon.resize((size, size), Image.LANCZOS).save(f"static/icon-{size}.png")
        print(f"static/icon-{size}.png 생성")


if __name__ == "__main__":
    build()
