# -*- coding: utf-8 -*-
"""
生成程序图标 assets/icon.ico（纯标准库实现，无需 Pillow）

图案：蓝色圆角方形底 + 居中金色五角星（4 倍超采样抗锯齿）
用法：python tools/make_icon.py
"""
import math
import os
import struct

SIZE = 64
SS = 4                      # 超采样倍数
BG = (0x37, 0x8A, 0xDD)     # 蓝 #378ADD
STAR = (0xEF, 0x9F, 0x27)   # 金 #EF9F27
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def rounded_square_hit(x, y, size, radius):
    """点是否落在圆角方形内（坐标以像素中心计）"""
    r = size - 1
    cx = min(max(x, radius), r - radius)
    cy = min(max(y, radius), r - radius)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= radius * radius


def star_points(cx, cy, outer, inner, rotate=-90.0):
    pts = []
    for i in range(10):
        ang = math.radians(rotate + i * 36.0)
        rad = outer if i % 2 == 0 else inner
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return pts


def point_in_poly(x, y, pts):
    """射线法判断点是否在多边形内"""
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def build_image():
    big = SIZE * SS
    star = star_points(big / 2.0, big / 2.0 + 1.5, big * 0.33, big * 0.14)
    radius = big * 0.20

    px = [[(0, 0, 0, 0)] * SIZE for _ in range(SIZE)]
    for by in range(SIZE):
        for bx in range(SIZE):
            r = g = b = a = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = bx * SS + sx + 0.5
                    y = by * SS + sy + 0.5
                    if not rounded_square_hit(x, y, big, radius):
                        continue
                    if point_in_poly(x, y, star):
                        c = STAR
                    else:
                        c = BG
                    r += c[0]
                    g += c[1]
                    b += c[2]
                    a += 255
            n = SS * SS
            px[by][bx] = (r // n, g // n, b // n, a // n)
    return px


def write_ico(px, path):
    w = h = SIZE
    # BITMAPINFOHEADER，biHeight 为 2 倍（含 AND 掩码区）
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    # 像素数据：BGRA，自下而上
    body = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[y][x]
            body += bytes((b, g, r, a))
    # AND 掩码：1bpp，每行补足 4 字节，全 0（不透明由 alpha 决定）
    row_bytes = ((w + 31) // 32) * 4
    mask = bytes(row_bytes * h)
    img = header + bytes(body) + mask

    icondir = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", w if w < 256 else 0, h if h < 256 else 0,
                        0, 0, 1, 32, len(img), 6 + 16)
    with open(path, "wb") as fp:
        fp.write(icondir + entry + img)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    px = build_image()
    path = os.path.join(OUT_DIR, "icon.ico")
    write_ico(px, path)
    print("已生成图标：%s（%d 字节）" % (path, os.path.getsize(path)))


if __name__ == "__main__":
    main()
