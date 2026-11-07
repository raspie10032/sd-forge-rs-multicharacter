# SPDX-License-Identifier: GPL-3.0-only
"""Versioned data-only presets; no Forge, torch, paths or code execution."""
from dataclasses import asdict, dataclass, field
import json
import math
import re

MAX_CHARACTERS = 10
MAX_JSON_BYTES = 128 * 1024
INFOTEXT_KEY = "RS MultiCharacter"


def number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be finite and in [{low}, {high}].")
    return float(value)


@dataclass(frozen=True)
class Character:
    enabled: bool = True
    prompt: str = ""
    x: float = 0.5
    y: float = 0.5
    box: tuple | None = None  # normalized left, top, right, bottom
    lora: str = "None"
    strength: float = 1.0
    clip_strength: float = 1.0

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("Character enabled must be true or false.")
        if not isinstance(self.prompt, str) or len(self.prompt) > 16000:
            raise ValueError("Character prompt must be text of at most 16000 characters.")
        if re.search(r"<\s*(?:lora|lyco|hypernet)\s*:", self.prompt, re.I):
            raise ValueError("Choose character LoRA in its LoRA field; inline network tags are unsupported.")
        number(self.x, 0, 1, "X")
        number(self.y, 0, 1, "Y")
        number(self.strength, -3, 3, "LoRA strength")
        number(self.clip_strength, -3, 3, "Text LoRA strength")
        if not isinstance(self.lora, str) or not self.lora or len(self.lora) > 512:
            raise ValueError("LoRA must be a name from Forge's LoRA list.")
        if self.box is not None:
            if not isinstance(self.box, (tuple, list)) or len(self.box) != 4:
                raise ValueError("Box needs [left, top, right, bottom].")
            box = tuple(number(v, 0, 1, "Box coordinate") for v in self.box)
            if box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError("Box must have positive width and height.")
            object.__setattr__(self, "box", box)
            if not (math.isclose(self.x, (box[0]+box[2])/2, abs_tol=1e-9) and
                    math.isclose(self.y, (box[1]+box[3])/2, abs_tol=1e-9)):
                raise ValueError("Character X/Y must match the box center, as in the original sampler.")

    @property
    def active(self):
        return self.enabled and bool(self.prompt.strip())

    @property
    def lora_key(self):
        return (self.lora, float(self.strength)) if self.lora != "None" and self.strength != 0 else None


@dataclass(frozen=True)
class Settings:
    # Match the original ComfyUI sampler. Explicit PNG/preset values win.
    common_prior: float = 0.05
    character_gain: float = 1.7
    separation: float = 0.9
    hold_steps: int = 3
    decay: float = 0.2
    lora_mode: str = "precision"

    def __post_init__(self):
        if self.lora_mode not in ("normal", "precision"):
            raise ValueError("LoRA mode must be normal or precision.")
        number(self.common_prior, 0, 1, "Common prior")
        number(self.character_gain, 1, 3, "Character gain")
        number(self.separation, 0, 0.99, "Separation")
        number(self.decay, 0.01, 1, "Boundary decay")
        if type(self.hold_steps) is not int or not 1 <= self.hold_steps <= 150:
            raise ValueError("Boundary hold must be an integer in [1, 150].")


@dataclass(frozen=True)
class Config:
    characters: tuple[Character, ...] = field(default_factory=tuple)
    settings: Settings = field(default_factory=Settings)
    version: int = 1
    pose3d_json: str | None = None

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError("Unsupported RS MultiCharacter preset version.")
        if not isinstance(self.settings, Settings):
            raise ValueError("Invalid settings.")
        if len(self.characters) > MAX_CHARACTERS or any(not isinstance(c, Character) for c in self.characters):
            raise ValueError("A preset supports at most ten characters.")
        object.__setattr__(self, "characters", tuple(self.characters))
        if self.pose3d_json is not None:
            if not isinstance(self.pose3d_json, str):
                raise ValueError("3D scene must be JSON text.")
            from .shared.pose3d import read_scene
            read_scene(self.pose3d_json)

    @property
    def active(self):
        return tuple(c for c in self.characters if c.active)

    def validate_generation(self):
        if not self.active:
            raise ValueError("Enable at least one character and enter its prompt. / 캐릭터 프롬프트를 입력하세요.")

    def to_build_pipe(self):
        """Use the original immutable builder, including separate model/TE LoRA."""
        from .shared.character_builder import BuildPipe, update_slot
        pipe = BuildPipe(prompt_count=MAX_CHARACTERS, pose3d_json=self.pose3d_json,
                         lora_application_mode=self.settings.lora_mode)
        for i, c in enumerate(self.characters, 1):
            pipe = update_slot(pipe, i, enabled=c.active, prompt=c.prompt, x=c.x, y=c.y,
                               geometry="box" if c.box else "point",
                               width=c.box[2]-c.box[0] if c.box else .4,
                               height=c.box[3]-c.box[1] if c.box else .8,
                               lora_name=c.lora, strength_model=c.strength, strength_clip=c.clip_strength)
        if self.pose3d_json:
            from .pose import apply_pose_masks
            pipe = apply_pose_masks(pipe, self.pose3d_json)
        return pipe

    def to_pipe(self):
        from .shared.character_builder import finalize
        return finalize(self.to_build_pipe(), apply_cameras=False)

    def to_json(self, pretty=False):
        return json.dumps(asdict(self), ensure_ascii=True, allow_nan=False,
                          indent=2 if pretty else None, separators=None if pretty else (",", ":"))

    @classmethod
    def from_json(cls, value):
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("Preset must be JSON text no larger than 128 KiB.")
        try:
            data = json.loads(value)
            if not isinstance(data, dict) or set(data) - {"version", "characters", "settings", "pose3d_json"}:
                raise ValueError("Unrecognized preset fields.")
            if "version" not in data or "characters" not in data:
                raise ValueError("Preset needs version and characters.")
            if not isinstance(data["characters"], list) or len(data["characters"]) > MAX_CHARACTERS:
                raise ValueError("Preset characters must be a list of at most ten slots.")
            return cls(tuple(Character(**row) for row in data["characters"]),
                       Settings(**data.get("settings", {})), data["version"], data.get("pose3d_json"))
        except (TypeError, KeyError, json.JSONDecodeError, RecursionError) as error:
            raise ValueError(f"Invalid RS MultiCharacter preset: {error}") from error


def defaults():
    return Config(tuple(Character(enabled=i < 2, x=(i + 0.5) / 2 if i < 2 else 0.5)
                        for i in range(MAX_CHARACTERS)))


def fit_box(x, y, width, height):
    """Move the center inward, preserving size, including disabled UI slots."""
    x = round(min(1 - width / 2, max(width / 2, x)), 12)
    y = round(min(1 - height / 2, max(height / 2, y)), 12)
    box = tuple(round(min(1., max(0., v)), 12) for v in
                (x - width / 2, y - height / 2, x + width / 2, y + height / 2))
    return x, y, box


def from_ui(values):
    if len(values) != 7 + MAX_CHARACTERS * 10:
        raise ValueError("RS MultiCharacter UI/API argument count mismatch.")
    prior, gain, separation, hold, decay = values[:5]
    hold_value = number(hold, 1, 150, "Boundary hold")
    if not hold_value.is_integer():
        raise ValueError("Boundary hold must be an integer.")
    chars = []
    for i in range(MAX_CHARACTERS):
        enabled, prompt, x, y, kind, width, height, lora, strength, clip_strength = values[5 + i*10:15 + i*10]
        if kind not in ("Point", "Box"):
            raise ValueError("Region type must be Point or Box.")
        number(x, 0, 1, "X")
        number(y, 0, 1, "Y")
        width = number(width, 0.01, 1, "Box width")
        height = number(height, 0.01, 1, "Box height")
        if kind == "Box":
            x, y, box = fit_box(x, y, width, height)
        else:
            box = None
        chars.append(Character(enabled, prompt, x, y, box, lora, strength, clip_strength))
    return Config(tuple(chars), Settings(prior, gain, separation, int(hold), decay, values[-1]),
                  pose3d_json=values[-2] or None)


def to_ui(config):
    s = config.settings
    values = [s.common_prior, s.character_gain, s.separation, s.hold_steps, s.decay]
    for i in range(MAX_CHARACTERS):
        c = config.characters[i] if i < len(config.characters) else Character(enabled=False)
        if c.box:
            left, top, right, bottom = c.box
            x, y, w, h = (round(v, 12) for v in
                          ((left+right)/2, (top+bottom)/2, right-left, bottom-top))
        else:
            x, y, w, h = c.x, c.y, 0.45, 0.9
        values.extend([c.enabled, c.prompt, x, y, "Box" if c.box else "Point", w, h, c.lora, c.strength, c.clip_strength])
    return [*values, config.pose3d_json or "", s.lora_mode]
