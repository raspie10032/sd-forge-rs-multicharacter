# SPDX-License-Identifier: GPL-3.0-only
"""Always-visible Forge extension. Heavy imports only when enabled."""

import logging

from modules import scripts

from rs_forge_mc import __version__
from rs_forge_mc import api  # noqa: F401 -- register local editor routes
from rs_forge_mc.config import INFOTEXT_KEY, from_ui

logger = logging.getLogger("rs_multicharacter")


class Script(scripts.Script):
    def title(self):
        return "RS MultiCharacter"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        from rs_forge_mc.ui import build

        return build(self, is_img2img)

    def after_component(self, component, **kwargs):
        for dimension in ("width", "height"):
            if component.elem_id in (f"txt2img_{dimension}", f"img2img_{dimension}"):
                if not hasattr(self, "rs_dimensions"):
                    self.rs_dimensions = {}
                self.rs_dimensions[dimension] = component

    def process(self, p, enabled, *values, **kwargs):
        if not enabled or getattr(p, "_rs_mc_detail_pass", False):
            return
        config = from_ui(values)
        camera = config.features.get("camera", {})
        if camera.get("enabled"):
            from rs_forge_mc.shared.camera_control import RSCameraControl

            def add(text):
                return RSCameraControl().apply(**camera, base_prompt=text)["result"][1]

            p.all_prompts = [add(text) for text in p.all_prompts]
            p.prompt = add(p.prompt) if isinstance(p.prompt, str) else p.prompt
        if config.features.get("syntax") == "NovelAI":
            from rs_forge_mc.shared.prompt_syntax import to_comfyui, parse_naiv4

            p.all_prompts = [to_comfyui(parse_naiv4(t)) for t in p.all_prompts]
            p.all_negative_prompts = [to_comfyui(parse_naiv4(t)) for t in p.all_negative_prompts]
        from rs_forge_mc.layout import resolve, native_prompt
        from rs_forge_mc.native_runtime import model_family

        if resolve(config, model_family(p.sd_model.forge_objects.unet)) == "moss_native":
            p.all_prompts = [native_prompt(config, t, p.width, p.height) for t in p.all_prompts]
            if isinstance(p.prompt, str):
                p.prompt = native_prompt(config, p.prompt, p.width, p.height)
        if config.features.get("progressive", {}).get("start_scale", 1.0) < 1.0:
            from rs_forge_mc.progressive import install

            install(p, config)
        p._rs_mc_config = config

    def postprocess_image(self, p, pp, *args):
        config = getattr(p, "_rs_mc_config", None)
        if (
            config
            and config.features.get("detailer", {}).get("enabled")
            and not getattr(p, "_rs_mc_detail_pass", False)
        ):
            from rs_forge_mc.detail import run

            pp.image, report = run(pp.image, p, config)
            p.extra_generation_params["RS detailer report"] = __import__("json").dumps(
                report, ensure_ascii=True
            )

    def process_before_every_sampling(self, p, enabled, *values, **kwargs):
        if not enabled:
            return
        if getattr(p, "_ad_inner", False) or getattr(p, "_rs_mc_detail_pass", False):
            return
        # Neo resets forge_objects from its LoRA base before each pass, so the
        # new clone belongs to this batch/pass (txt2img, img2img or Hires).
        original = p.sd_model.forge_objects.unet
        try:
            from rs_forge_mc.progressive import attach

            attach(p)
            from rs_forge_mc.integration import install

            config = from_ui(values)
            config.validate_generation()
            if kwargs.get("x") is None:
                raise ValueError("Forge Neo did not provide the current sampling latent.")
            if p.batch_size != 1:
                raise ValueError("RS routing uses batch size 1; use batch count for multiple images.")
            patched, runtime = install(p, config, kwargs["x"])
            p.sd_model.forge_objects.unet = patched
            p._rs_mc_runtime = runtime
            p._rs_mc_restore = (original, patched)
            p.extra_generation_params[INFOTEXT_KEY] = config.to_json()
            p.extra_generation_params["RS MultiCharacter version"] = __version__
            p.extra_generation_params["RS MultiCharacter LoRA mode"] = runtime.audit["effective_lora_mode"]
            if "lora_fallback_reason" in runtime.audit:
                reason = runtime.audit["lora_fallback_reason"]
                logger.warning("RS Normal LoRA uses Precision fallback: %s", reason)
                p.extra_generation_params["RS MultiCharacter LoRA fallback"] = reason
        except Exception as error:
            # Neo reports and swallows Script hook exceptions. A failing model
            # wrapper propagates the useful error through the sampling call.
            # state.interrupt() would skip that wrapper and make Neo fail later
            # with an unrelated "NoneType is not iterable" instead.
            failed = original.clone()

            def fail(*args, message=str(error), **kw):
                raise RuntimeError(f"RS MultiCharacter generation cancelled: {message}")

            failed.set_model_unet_function_wrapper(fail)
            p.sd_model.forge_objects.unet = failed
            p._rs_mc_restore = (original, failed)
            raise RuntimeError(f"RS MultiCharacter: {error}") from error

    def postprocess(self, p, processed, *args):
        sampler_restore = getattr(p, "_rs_mc_sampler_restore", None)
        if sampler_restore:
            sampler_restore()
        restore = getattr(p, "_rs_mc_restore", None)
        if restore and p.sd_model.forge_objects.unet is restore[1]:
            p.sd_model.forge_objects.unet = restore[0]
        runtime = getattr(p, "_rs_mc_runtime", None)
        if runtime:
            runtime.clear()
            api.LAST_AUDIT.clear()
            api.LAST_AUDIT.update(runtime.audit)
            logger.info("RS MultiCharacter audit: %s", runtime.audit)
        for name in ("_rs_mc_runtime", "_rs_mc_restore", "_rs_mc_config", "_rs_mc_sampler_restore"):
            p.__dict__.pop(name, None)
