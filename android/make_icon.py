# -*- coding: utf-8 -*-
"""生成 AI信息雷达 启动图标（雷达风格），输出 mipmap 各密度 PNG。"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "res"

# 各密度尺寸
DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def draw_icon(size):
    """在深海军蓝圆角背景上画雷达：同心环 + 扫描线 + 中心亮点。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角矩形背景
    pad = size * 0.02
    radius = size * 0.20
    d.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=(15, 35, 54, 255),   # 深海军蓝 #0f2336
    )

    cx = cy = size / 2
    # 同心环（从外到内）
    rings = [0.40, 0.29, 0.18]
    for r in rings:
        rr = size * r
        d.ellipse(
            [cx - rr, cy - rr, cx + rr, cy + rr],
            outline=(46, 204, 113, 255),   # 绿色环
            width=max(2, int(size * 0.015)),
        )

    # 扫描扇形（从 12 点方向顺时针 60 度，半透明）
    start_deg = -90
    end_deg = -30
    scan_radius = size * 0.40
    d.pieslice(
        [cx - scan_radius, cy - scan_radius, cx + scan_radius, cy + scan_radius],
        start=start_deg,
        end=end_deg,
        fill=(46, 204, 113, 90),
    )

    # 扫描边缘线
    for deg in (start_deg, end_deg):
        rad = math.radians(deg)
        x = cx + math.cos(rad) * scan_radius
        y = cy + math.sin(rad) * scan_radius
        d.line([cx, cy, x, y], fill=(46, 204, 113, 255), width=max(2, int(size * 0.012)))

    # 中心亮点（红点，呼应新闻红）
    dot = size * 0.05
    d.ellipse(
        [cx - dot, cy - dot, cx + dot, cy + dot],
        fill=(184, 34, 26, 255),
    )

    return img


def main():
    for folder, size in DENSITIES.items():
        d = OUT / folder
        d.mkdir(parents=True, exist_ok=True)
        draw_icon(size).save(d / "ic_launcher.png")
        print(f"  {folder}: {size}x{size} ✓")


if __name__ == "__main__":
    main()
