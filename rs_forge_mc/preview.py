# SPDX-License-Identifier: GPL-3.0-only
"""Small, cached SVGs using the sampler's own numbered mask pipeline."""

from dataclasses import replace
from functools import lru_cache

from .geometry import membership
from .shared.layout import effective_centers

COLORS = (
    "#d96d9f",
    "#6b9ee8",
    "#54b59b",
    "#d6a24d",
    "#9e82dc",
    "#d77e66",
    "#5faec0",
    "#a8af5c",
    "#c77bce",
    "#898f9f",
)


@lru_cache(maxsize=32)
def _render(config, width, height):
    slots = [
        i
        for i, c in enumerate(config.characters)
        if c.enabled and config.features.get("slots", {}).get(str(i + 1), {}).get("kind") != "text"
    ] + [
        i
        for i, c in enumerate(config.characters)
        if c.enabled and config.features.get("slots", {}).get(str(i + 1), {}).get("kind") == "text"
    ]
    cells, marks = [], []
    if slots:
        chars = config.to_pipe().regions
        centers, _ = effective_centers(chars)
        scale = 64 / max(width, height)
        cols, rows = max(8, round(width * scale)), max(8, round(height * scale))
        masks = membership(chars, rows, cols, "cpu")
        codes = sum(mask.long() * (1 << i) for i, mask in enumerate(masks)).tolist()
        for row, line in enumerate(codes):
            col = 0
            while col < cols:
                code, end = line[col], col + 1
                while end < cols and line[end] == code:
                    end += 1
                if code:
                    owners = [slots[i] for i in range(len(slots)) if code & (1 << i)]
                    rgb = [tuple(int(COLORS[i][c : c + 2], 16) for c in (1, 3, 5)) for i in owners]
                    color = "#" + "".join(f"{round(sum(c) / len(rgb)):02x}" for c in zip(*rgb))
                    cells.append(
                        f'<rect x="{col * width / cols:g}" y="{row * height / rows:g}" '
                        f'width="{(end - col) * width / cols:g}" height="{height / rows:g}" '
                        f'fill="{color}" opacity=".5" shape-rendering="crispEdges" '
                        f'data-rs-slot="{owners[0]}"/>'
                    )
                col = end
        radius = min(width, height) * 0.035
        for slot, c, (x, y) in zip(slots, chars, centers):
            if c.bbox:
                left, top, right, bottom = c.bbox
                marks.append(
                    f'<rect x="{left * width:g}" y="{top * height:g}" '
                    f'width="{(right - left) * width:g}" height="{(bottom - top) * height:g}" '
                    f'fill="none" stroke="{COLORS[slot]}" stroke-width="{radius / 6:g}"/>'
                )
            label = f"캐릭터 {slot + 1} (프롬프트 입력)"
            marks.append(
                f'<g role="button" tabindex="0" data-rs-slot="{slot}" aria-label="{label}">'
                f'<title>{label}</title><circle cx="{x * width:g}" cy="{y * height:g}" '
                f'r="{radius:g}" fill="{COLORS[slot]}"/>'
                f'<text x="{x * width:g}" y="{y * height + radius * 0.35:g}" text-anchor="middle" '
                f'fill="white" font-size="{radius * 1.1:g}">{slot + 1}</text></g>'
            )
    return "".join(cells + marks)


def preview(config, ident="t2i", width=1024, height=1024):
    def dimension(value):
        # A Gradio number briefly becomes 0/None while the user replaces it.
        try:
            return min(8192, max(64, int(value)))
        except (TypeError, ValueError, OverflowError):
            return 1024

    width, height = dimension(width), dimension(height)
    # Prompt text and LoRA selection cannot invalidate a geometry preview or
    # defeat its cache. Empty, enabled slots are shown so users can place them.
    geometry = replace(
        config,
        characters=tuple(
            replace(c, prompt="preview", lora="None", strength=1.0, clip_strength=1.0)
            for c in config.characters
        ),
    )
    mode = "3D 실루엣" if config.pose3d_json else "위치 · 박스"
    return (
        f'<div class="rs-mc-preview" data-rs-target="{ident}" data-region-mode="'
        f'{"pose" if config.pose3d_json else "xy"}">'
        f'<div class="rs-mc-preview-heading"><strong>적용 영역: {mode}</strong>'
        f"<span>{width} × {height}</span></div>"
        f'<svg viewBox="0 0 {width} {height}" role="group" aria-label="캐릭터 적용 영역 미리보기" '
        f'style="aspect-ratio:{width}/{height};width:min(100%,{300 * width / height:g}px);'
        "height:auto;display:block;margin:8px auto;background:#20232b;"
        f'border-radius:8px">{_render(geometry, width, height)}</svg>'
        "<small>입력 전 캐릭터도 표시합니다. 겹친 영역은 색을 섞어 표시합니다.</small></div>"
    )
