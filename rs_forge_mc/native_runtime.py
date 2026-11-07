# SPDX-License-Identifier: GPL-3.0-only
"""Forge execution boundary for original RS Anima/U-Net/joint routing engines."""

from contextlib import contextmanager, nullcontext
import torch

from .anima_math import comfy_math
from .geometry import prediction_masks
from .runtime import RUNTIME_LOCK, text_tensor
from .shared.layout import character_masks, effective_centers
from .shared.region_mask import explicit_region


def model_family(unet):
    name = type(unet.model.diffusion_model).__name__
    if name == "Anima":
        return "Anima"
    if name in ("Krea2", "SingleStreamDiT"):
        return "Krea2"
    if name in ("MOSSImage", "MossImage", "MossImageModel"):
        return "MOSS"
    if name == "IntegratedFluxTransformer2DModel":
        return "FLUX2" if unet.model.diffusion_model.global_modulation else "FLUX1"
    if name == "Flux":
        return "FLUX1"
    if name == "Flux2":
        return "FLUX2"
    if name == "Flux3":
        return "FLUX3"
    if name in ("UNetModel", "IntegratedUNet2DConditionModel"):
        # Forge's estimated family is authoritative; channel count excludes
        # inpainting/refiner variants rather than guessing from filenames.
        config = unet.model.config
        family = type(config).__name__
        if getattr(config, "unet_config", {}).get("in_channels", 4) != 4:
            raise ValueError("Use a four-channel base U-Net.")
        return "SDXL" if "XL" in family else "SD1.5"
    raise ValueError(f"Unsupported diffusion architecture: {name}")


class Executor:
    def __init__(self, fn, obj):
        self.fn, self.class_obj = fn, obj

    def __call__(self, *args, **kwargs):
        return self.fn(*args, **kwargs)


class KreaView:
    def __init__(self, dm):
        self.dm = dm

    def __getattr__(self, key):
        return getattr(self.dm, key)

    def _unpack_context(self, context):
        if context.ndim == 4:
            return context
        b, n, _ = context.shape
        return context.reshape(b, n, self.dm.txtlayers, self.dm.txtdim)


class AnimaView:
    """Only the old fps keyword differs; tensors/modules are the real Forge ones."""

    def __init__(self, dm):
        self.dm = dm

    def __getattr__(self, key):
        return getattr(self.dm, key)

    @property
    def model_channels(self):
        return self.dm.blocks[0].self_attn.q_proj.in_features

    @property
    def num_heads(self):
        return self.dm.blocks[0].self_attn.n_heads

    def prepare_embedded_sequence(self, x, fps=None, padding_mask=None):
        return self.dm.prepare_embedded_sequence(x, padding_mask=padding_mask)


@contextmanager
def anima_ops(dm):
    saved = []
    try:
        for block_index, block in enumerate(dm.blocks):
            for module in (block.cross_attn, block.self_attn):
                for key in ("attn_op", "torch_attention_op"):
                    saved.append((module, key, key in module.__dict__, module.__dict__.get(key)))
                module.attn_op = module.torch_attention_op

                def dispatch(q, k, v, transformer_options=None, module=module, index=block_index):
                    return module.attn_op(
                        q, k, v, transformer_options={**(transformer_options or {}), "block_index": index}
                    )

                module.torch_attention_op = dispatch
        yield
    finally:
        for module, key, present, value in reversed(saved):
            if present:
                setattr(module, key, value)
            else:
                module.__dict__.pop(key, None)


@contextmanager
def krea_blocks(dm):
    """Neo omits the block marker used by the shared joint routing engine."""
    handles = []
    try:
        for index, block in enumerate(dm.blocks):

            def mark(module, args, kwargs, index=index):
                kwargs["transformer_options"] = {
                    **kwargs.get("transformer_options", {}),
                    "block_index": index,
                }
                return args, kwargs

            handles.append(block.register_forward_pre_hook(mark, with_kwargs=True))
        yield
    finally:
        for handle in handles:
            handle.remove()


class NativeRuntime:
    def __init__(self, config, contexts, plans, family, pipe=None, size=(1024, 1024)):
        self.config, self.family = config, family
        from .layout import resolve

        self.native_layout = resolve(config, family) == "moss_native"
        self.pipe = pipe or config.to_pipe()
        self.characters = self.pipe.regions
        self.contexts = tuple(text_tensor(c).detach().cpu() for c in contexts)
        self.plans = plans
        self.audit = {
            "family": family,
            "model_calls": 0,
            "prediction_passes": 0,
            "restored_calls": 0,
            "forwards": [],
            "cross_calls": 0,
            "self_calls": 0,
            "restored_forwards": 0,
            "token_grids": [],
            "grids": [],
        }
        if config.features.get("interaction"):
            self.audit["interaction"] = config.features["interaction"]
        self.pose, self.part_captions = __import__("rs_forge_mc.features", fromlist=["part_plan"]).part_plan(
            self.pipe
        )
        self.audit["pose_parts"] = {"captions": self.part_captions} if self.pose else None
        centers, _ = effective_centers(self.characters)
        self.feather = config.features.get("schedule", {}).get("region_feather", 0.04)
        self.masks = character_masks(self.characters, centers, *size, self.feather)
        self.boxes = tuple(explicit_region(c) for c in self.characters)
        s = config.settings
        settings = dict(
            initial_common_prior=s.common_prior,
            initial_character_gain=s.character_gain,
            initial_spatial_separation=s.separation,
            boundary_hold_steps=s.hold_steps,
            boundary_decrement=s.decay,
            common_after_step3_boost=config.features.get("schedule", {}).get("common_boost", 0.1),
        )
        conditions = [(c, {}) for c in self.contexts]
        if family == "Anima":
            from .shared.engine import AnimaRouting

            self.routing = AnimaRouting(
                conditions,
                self.masks,
                "character_first",
                self.audit,
                0,
                **settings,
                common_weight_schedule="step_3x0.2",
                spatial_separation_schedule="hold_decay",
                boxes=self.boxes,
            )
            self.routing.contexts = self.contexts
            self.routing.pose = self.pose
        elif family in ("SDXL", "SD1.5"):
            from .shared.sdxl_engine import SDXLRouting

            self.routing = SDXLRouting(conditions, self.masks, settings, self.audit, family, boxes=self.boxes)
            self.routing.pose = self.pose
        elif family in ("Krea2", "MOSS"):
            from .shared.joint_engine import JointRouting

            self.routing = JointRouting(
                family, conditions, self.masks, settings, self.audit, boxes=self.boxes
            )
        else:
            from .shared.flux_engine import FluxRouting

            self.routing = FluxRouting(
                family,
                conditions,
                self.masks,
                settings,
                self.audit,
                boxes=self.boxes,
                regional_loras=bool(plans),
            )
            self.routing.redux_references = []
        self.routing.reference_audit = {}
        self.audit.setdefault("text_refiner_calls", 0)
        self.audit["layout_method"] = "moss_native" if self.native_layout else "regional"
        self.audit["regional_controls_applied"] = not self.native_layout
        self.shared_lora = None
        if (
            plans
            and s.lora_mode == "normal"
            and family == "Anima"
            and all(hasattr(p, "factors") for p in plans.values())
        ):
            from .shared_lora import SharedLora, SharedLoraUnsupported

            try:
                self.shared_lora = SharedLora(plans, self.characters)
            except SharedLoraUnsupported as error:
                self.audit["lora_fallback_reason"] = str(error)
        self.audit.update(
            requested_lora_mode=s.lora_mode,
            effective_lora_mode="normal" if self.shared_lora else "precision" if plans else "none",
        )
        self.reference = None
        self.reference_bank = None
        self.pose_runtime = None
        self.legacy_reference = None
        self.reference_values = {}

    def install(self, unet):
        dm = unet.model.diffusion_model
        if self.family in ("SDXL", "SD1.5"):
            from backend.nn.unet import BasicTransformerBlock

            for name, modules in (
                ("input", dm.input_blocks),
                ("middle", [dm.middle_block]),
                ("output", dm.output_blocks),
            ):
                for index, module in enumerate(modules):
                    if any(isinstance(m, BasicTransformerBlock) for m in module.modules()):
                        unet.set_model_attn1_replace(self.routing.spatial, name, index)
                        unet.set_model_attn2_replace(self.routing.cross, name, index)
            if self.routing.reference is not None:
                number = 0
                self.routing.reference_modules = {}
                for name, modules in (
                    ("input", dm.input_blocks),
                    ("output", dm.output_blocks),
                    ("middle", [dm.middle_block]),
                ):
                    for index, module in enumerate(modules):
                        for ti, _ in enumerate(
                            m for m in module.modules() if isinstance(m, BasicTransformerBlock)
                        ):
                            key = (name, index, ti) if self.family == "SDXL" else (name, index)
                            self.routing.reference_modules[key] = str(2 * number + 1)
                            unet.set_model_attn2_replace(
                                self.routing.cross, name, index, ti if self.family == "SDXL" else None
                            )
                            number += 1
                self.routing.reference.audit["mapped_blocks"] = number
        elif self.family != "Anima" and not self.native_layout:
            unet.model_options.setdefault("transformer_options", {})["optimized_attention_override"] = (
                self.routing.attention
            )
            if self.family in ("FLUX1", "FLUX2"):
                unet.model_options["transformer_options"].setdefault("patches", {}).setdefault(
                    "post_input", []
                ).append(self.routing.text_positions)
        unet.set_model_unet_function_wrapper(self)

    def __call__(self, apply_model, args):
        with RUNTIME_LOCK:
            return self.forward(apply_model, args)

    def forward(self, apply_model, args):
        dm = apply_model.__self__.diffusion_model
        x, t = args["input"], args["timestep"]
        c = dict(args["c"])
        opts = dict(c.get("transformer_options", {}))
        kinds = args.get("cond_or_uncond") or opts.get("cond_or_uncond")
        if not kinds or x.shape[0] % len(kinds):
            raise ValueError("Invalid Forge CFG rows.")
        rows = [k for k in kinds for _ in range(x.shape[0] // len(kinds))]
        sigma = opts.get("sigmas", t)
        schedule = opts.get("sampling_sigmas")
        if schedule is None:
            raise ValueError("Forge did not expose sampling_sigmas.")
        schedule = schedule.detach().cpu().tolist()
        self.routing.sigmas = [float(s) for s in schedule if s > 0]
        opts.update(cond_or_uncond=rows, sigmas=sigma)
        if self.reference is not None:
            opts["rs_reference_compact_spatial"] = True
        c["transformer_options"] = opts
        original = dm.forward
        present = "forward" in dm.__dict__
        previous = dm.__dict__.get("forward")
        view = AnimaView(dm) if self.family == "Anima" else KreaView(dm) if self.family == "Krea2" else dm

        def execute(x, t, context, *pos, **kwargs):
            keys = {
                "SDXL": ("y", "control", "transformer_options"),
                "SD1.5": ("y", "control", "transformer_options"),
                "Krea2": ("attention_mask", "ref_latents", "transformer_options"),
                "MOSS": ("transformer_options",),
            }.get(self.family, ())
            kwargs.update(zip(keys, pos))
            kwargs.pop("fps", None)
            if self.family == "Krea2":
                kwargs.pop("ref_latents", None)
                context = view._unpack_context(context)
            return original(x, t, context=context, **kwargs)

        base = Executor(execute, view)

        def routed(x, t, context=None, **kwargs):
            options = kwargs.get("transformer_options", {})
            options.update(cond_or_uncond=rows, sigmas=sigma)
            kwargs["transformer_options"] = options
            if self.native_layout:
                return base(x, t, context, **kwargs)
            if self.family == "Anima":
                context = text_tensor(context)
                target = base
                if self.reference is not None:
                    target = Executor(lambda *a, **kw: self.reference.forward(base, *a, **kw), view)
                    kwargs["rs_anima_ref_frame"] = (
                        None
                        if self.reference_bank is None
                        else self.reference.reference[:, :, self.reference_bank : self.reference_bank + 1]
                    )
                    if self.reference_bank is not None:
                        options["rs_reference_bank"] = self.reference_bank
                    routed_reference = Executor(lambda *a, **kw: self.routing.forward(target, *a, **kw), view)
                    return self.reference.mark(routed_reference, x, t, context, **kwargs)
                if getattr(self.routing, "role_kv_runtime", None) is not None:
                    target = Executor(
                        lambda *a, **kw: self.routing.role_kv_runtime.forward(base, *a, **kw), view
                    )
                if self.legacy_reference is not None:
                    target = Executor(lambda *a, **kw: self.legacy_reference.forward(base, *a, **kw), view)
                return self.routing.forward(target, x, t, context, **kwargs)
            if self.family in ("SDXL", "SD1.5"):
                return self.routing.forward(base, x, t, context, **kwargs)
            if self.family == "MOSS":
                return self.routing.moss_forward(base, x, t, context, **kwargs)
            if self.family == "Krea2":
                if context.ndim == 4:
                    context = context.flatten(2)
                return self.routing.krea_forward(base, x, t, context, **kwargs)
            method = self.routing.flux3_forward if self.family == "FLUX3" else self.routing.flux_forward
            return method(base, x, t, context, **kwargs)

        dm.forward = routed
        shape = x.shape[-2:]
        weights = prediction_masks(self.characters, *shape, x.device, feather=self.feather)
        lengths = [c["c_crossattn"].shape[-2]] + [ct.shape[1] for ct in self.contexts]
        grid = [v // getattr(dm, "patch_spatial", 1) for v in shape]
        self.audit["model_calls"] += 1
        try:
            with (
                comfy_math(dm) if self.family == "Anima" else nullcontext(),
                anima_ops(dm) if self.family == "Anima" else nullcontext(),
                krea_blocks(dm) if self.family == "Krea2" else nullcontext(),
            ):

                def predict():
                    if self.shared_lora is not None:
                        with self.shared_lora.installed(apply_model.__self__, weights, grid, lengths):
                            value = apply_model(x, t, **c)
                        self.audit["prediction_passes"] += 1
                        return value
                    if not self.plans:
                        self.audit["prediction_passes"] += 1
                        return apply_model(x, t, **c)
                    value = torch.zeros_like(x)
                    for key, mask in weights:
                        ctx = (
                            nullcontext()
                            if key is None
                            else self.plans[key[0]].applied(apply_model.__self__, key[1])
                        )
                        with ctx:
                            part = apply_model(x, t, **c)
                        value += part * mask.to(part).reshape(1, 1, *([1] * (x.ndim - 4)), *shape)
                        self.audit["prediction_passes"] += 1
                    return value

                with nullcontext():
                    from .learned_pose import scope as pose_scope

                    with pose_scope(self, apply_model.__self__, x, sigma):
                        result = predict()
                        if self.reference:
                            for bank in range(self.reference.reference.shape[2]):
                                self.reference_bank = bank
                                value = predict()
                                for index, kind in enumerate(rows):
                                    self.reference_values[bank, kind] = value[index : index + 1]
                            self.reference_bank = None
                return result
        finally:
            if present:
                dm.forward = previous
            else:
                dm.__dict__.pop("forward", None)
            self.audit["restored_calls"] += 1

    def reference_cfg(self, args):
        import torch.nn.functional as F

        positive, negative = args["cond_denoised"], args["uncond_denoised"]
        base = negative + (positive - negative) * args["cond_scale"]
        result = base.clone()
        raw = F.interpolate(
            self.masks[list(self.reference.slots)].float()[:, None], size=base.shape[-2:], mode="nearest"
        ).to(base)[:, 0]
        weights = raw / raw.sum(0, keepdim=True).clamp_min(1)
        dims = tuple(range(1, base.ndim))
        for bank, strength in enumerate(self.reference.strengths):
            pos = self.reference_values.get((bank, 0))
            neg = self.reference_values.get((bank, 1))
            if pos is None or neg is None:
                raise ValueError("Reference guidance needs both CFG branches.")
            guided = (
                negative + self.reference.plan.guidance * (neg - negative) + args["cond_scale"] * (pos - neg)
            )
            if self.reference.plan.correction == "apg":
                update = (guided - pos).double()
                unit = F.normalize(pos.double().flatten(1), dim=1).view_as(pos)
                guided = pos + (update - (update * unit).sum(dims, keepdim=True) * unit).to(pos.dtype)
            elif self.reference.plan.correction == "rescale":
                ratio = pos.std(dims, keepdim=True) / guided.std(dims, keepdim=True).clamp_min(1e-12)
                guided = 0.5 * guided * ratio + 0.5 * guided
            mask = weights[bank].reshape(1, 1, *([1] * (base.ndim - 4)), *base.shape[-2:])
            result += (guided - base) * mask * strength
        self.reference_values.clear()
        return args["input"] - result

    def clear(self):
        if self.reference:
            self.reference.clear()
        if getattr(self.routing, "role_kv_runtime", None):
            role = self.routing.role_kv_runtime
            role.banks = role.engine = role.grid = None
            role.latents.clear()
        self.routing.state = None
        if hasattr(self.routing, "pose_kv"):
            self.routing.pose_kv.clear()
        if self.pose_runtime:
            self.pose_runtime.clear()
        self.reference_values.clear()
        self.routing.contexts = None
