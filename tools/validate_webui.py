#!/usr/bin/env python3
"""Opt-in real GPU/API checks against an already-running local Forge Neo.

This performs image generation. It never starts a server or downloads models.
Browser UI/3D interaction must be checked separately.
"""
import argparse
import base64
from dataclasses import replace
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rs_forge_mc import __version__  # noqa: E402
from rs_forge_mc.config import Config, defaults, to_ui  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:7862')
    parser.add_argument('--lora', action='append', required=True, help='Repeat for two installed Anima Linear LoRAs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if len(args.lora) != 2:
        parser.error('Provide two --lora names from this WebUI registry.')
    args.output.mkdir(parents=True, exist_ok=True)

    def request(route, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(args.url + route, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=600) as response:
            return json.load(response)

    registry = {row['name'] for row in request('/sdapi/v1/loras')}
    if not set(args.lora) <= registry:
        parser.error(f'Unknown LoRA names. Registry: {sorted(registry)}')
    initial = defaults()
    chars = list(initial.characters)
    for i, hair in enumerate(('red', 'blue')):
        chars[i] = replace(chars[i], prompt=f'1girl, long {hair} hair, {hair} eyes, {hair} dress, standing, full body',
                           lora=args.lora[i], strength=.65, clip_strength=.65)
    config = Config(tuple(chars), initial.settings)
    base = dict(prompt='masterpiece, best quality, anime illustration, 2girls, standing in a sunny garden, full body',
                negative_prompt='low quality, blurry, extra limbs, text, watermark',
                steps=10, width=768, height=512, cfg_scale=4, seed=24681357,
                sampler_name='ER SDE', scheduler='Beta', batch_size=1, n_iter=1,
                do_not_save_samples=True, do_not_save_grid=True)
    report = dict(version=__version__, url=args.url, loras=args.lora,
                  checkpoint=request('/sdapi/v1/options')['sd_model_checkpoint'], cases=[])
    images = {}

    def save_report():
        (args.output/'api-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    def generate(name, active=False, cfg=config, route='txt2img', **extra):
        started = time.monotonic()
        payload = dict(base, **extra)
        payload['alwayson_scripts'] = {'RS MultiCharacter': {'args': [active, *to_ui(cfg)]}}
        response = request('/sdapi/v1/' + route, payload)
        assert response.get('images'), f'{name}: no output image'
        encoded = response['images'][0]
        raw = base64.b64decode(encoded.split(',', 1)[-1])
        image = Image.open(BytesIO(raw)).convert('RGB')
        images[name] = (encoded, image)
        (args.output/(name+'.png')).write_bytes(raw)
        info = json.loads(response['info'])
        metadata = info.get('infotexts', [''])[0]
        row = dict(name=name, seconds=round(time.monotonic()-started, 3), size=list(image.size),
                   pixel_sha256=hashlib.sha256(image.tobytes()).hexdigest(), infotext=metadata)
        if active:
            assert 'RS MultiCharacter version: ' + __version__ in metadata, metadata
        report['cases'].append(row)
        save_report()
        print(name, row['size'], row['seconds'], flush=True)
        return row

    before = generate('off-before')
    generate('precision-two-loras', active=True)
    normal = replace(config, settings=replace(config.settings, lora_mode='normal'))
    generate('normal-two-loras', active=True, cfg=normal)
    generate('hires-two-loras', active=True, enable_hr=True, hr_scale=1.25,
             hr_additional_modules=['Use same choices'],
             hr_upscaler='Latent', hr_second_pass_steps=4, denoising_strength=.4)
    generate('img2img-two-loras', active=True, route='img2img',
             init_images=[images['precision-two-loras'][0]], denoising_strength=.35)
    invalid = replace(config, characters=tuple(replace(c, prompt='') for c in config.characters))
    try:
        result = request('/sdapi/v1/txt2img', dict(base, alwayson_scripts={
            'RS MultiCharacter': {'args': [True, *to_ui(invalid)]}}))
        rejected = not result.get('images')
        details = {k: result.get(k) for k in ('error', 'detail') if result.get(k)}
    except urllib.error.HTTPError as error:
        rejected = error.code >= 400
        details = {'status': error.code, 'body': error.read().decode()[:1000]}
    report['invalid_empty_prompt'] = dict(rejected=rejected, details=details)
    assert rejected, 'Invalid enabled preset silently produced an image.'
    assert 'RS MultiCharacter generation cancelled' in str(details), details
    after = generate('off-after')
    report['off_after_normal_precision_hires_img2img_and_error_exact'] = before['pixel_sha256'] == after['pixel_sha256']
    report['passed'] = report['off_after_normal_precision_hires_img2img_and_error_exact']
    save_report()
    assert report['passed'], 'Extension OFF output changed after the checks.'
    print('PASS: OFF output restored exactly after both LoRA modes, Hires.fix, img2img and an invalid request.', flush=True)


if __name__ == '__main__':
    main()
