# SPDX-License-Identifier: GPL-3.0-only
"""Always-visible Forge extension. Heavy imports only when enabled."""
from contextlib import nullcontext
import logging

from modules import scripts, shared

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
        for dimension in ('width', 'height'):
            if component.elem_id in (f'txt2img_{dimension}', f'img2img_{dimension}'):
                if not hasattr(self, 'rs_dimensions'):
                    self.rs_dimensions = {}
                self.rs_dimensions[dimension] = component

    def process_before_every_sampling(self, p, enabled, *values, **kwargs):
        if not enabled:
            return
        if getattr(p, "_ad_inner", False):
            return
        # Neo resets forge_objects from its LoRA base before each pass, so the
        # new clone belongs to this batch/pass (txt2img, img2img or Hires).
        original = p.sd_model.forge_objects.unet
        try:
            from backend.args import dynamic_args
            from modules.prompt_parser import SdConditioning
            from rs_forge_mc.lora import load_plans
            from rs_forge_mc.runtime import RUNTIME_LOCK, install, validate_model

            config = from_ui(values)
            config.validate_generation()
            pipe = config.to_pipe()
            validate_model(original)
            if dynamic_args.ref_latents or getattr(shared.opts, "anima_do_reference", False):
                raise ValueError("Disable Anima image reference while using RS MultiCharacter alpha.")
            if getattr(dynamic_args, "nunchaku", False):
                raise ValueError("Nunchaku is unsupported for RS MultiCharacter alpha.")
            if kwargs.get("x") is None:
                raise ValueError("Forge Neo did not provide the current sampling latent.")
            height, width = (int(v)*8 for v in kwargs["x"].shape[-2:])
            clip = p.sd_model.forge_objects.clip
            with RUNTIME_LOCK:
                model_plans, text_plans = load_plans(original, clip, pipe.regions)
                contexts = []
                for character in pipe.regions:
                    plan = text_plans.get(character.lora_name)
                    scope = plan.applied(clip.cond_stage_model, character.lora_clip_strength) if plan else nullcontext()
                    prompt = SdConditioning([character.prompt], width=width, height=height,
                                            distilled_cfg_scale=getattr(p, "distilled_cfg_scale", None))
                    with scope:
                        context = p.sd_model.get_learned_conditioning(prompt)
                    if not isinstance(context, list) or len(context) != 1:
                        raise ValueError("Unexpected Anima character conditioning format.")
                    contexts.append(context[0].detach().cpu())
                patched, runtime = install(original, config, contexts, model_plans)
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
        restore = getattr(p, "_rs_mc_restore", None)
        if restore and p.sd_model.forge_objects.unet is restore[1]:
            p.sd_model.forge_objects.unet = restore[0]
        runtime = getattr(p, "_rs_mc_runtime", None)
        if runtime:
            logger.info("RS MultiCharacter audit: %s", runtime.audit)
        for name in ("_rs_mc_runtime", "_rs_mc_restore"):
            p.__dict__.pop(name, None)
