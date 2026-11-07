/* SPDX-License-Identifier: GPL-3.0-only */
(() => {
    'use strict';
    const editors = new Map();
    function syncState(id) {
        const root = document.getElementById(`rs_mc_${id}`);
        if (!root) return;
        const enabled = document.querySelector(`#rs_mc_enabled_${id} input`)?.checked;
        const state = enabled ? 'on' : 'off';
        if (root.dataset.rsState !== state) root.dataset.rsState = state;
        const message = enabled ? '사용 중 · 캐릭터 설정을 생성에 적용합니다.'
            : '꺼짐 · 설정을 편집할 수 있지만 생성에는 적용되지 않습니다.';
        const status = root.querySelector('.rs-mc-state');
        if (status && status.textContent !== message) status.textContent = message;
        for (let slot = 0; slot < 10; slot++) {
            const kind = document.querySelector(`#rs_mc_kind_${id}_${slot} input:checked`)?.value;
            const sizes = document.getElementById(`rs_mc_box_${id}_${slot}`);
            if (sizes && sizes.hidden !== (kind !== 'Box')) sizes.hidden = kind !== 'Box';
        }
    }
    function syncCards(id) {
        const list = document.querySelector(`.rs-mc-character-list[data-rs-target="${id}"]`);
        if (!list) return;
        let available = false;
        for (const card of list.querySelectorAll('.rs-mc-character-open')) {
            const slot = card.dataset.rsSlot;
            const on = document.querySelector(`#rs_mc_on_${id}_${slot} input`);
            if (!on) continue;
            const prompt = document.querySelector(`#rs_mc_prompt_${id}_${slot} textarea`)?.value.trim() || '';
            const loraRoot = document.querySelector(`#rs_mc_lora_${id}_${slot}`);
            const lora = loraRoot?.querySelector('.single-select')?.textContent.trim()
                || loraRoot?.querySelector('input')?.value || 'None';
            const summary = prompt || '눌러서 프롬프트 · LoRA 설정';
            const loraText = lora === 'None' ? 'LoRA 없음' : `LoRA · ${lora}`;
            if (card.hidden === on.checked) card.hidden = !on.checked;
            if (card.querySelector('.rs-mc-character-summary').textContent !== summary)
                card.querySelector('.rs-mc-character-summary').textContent = summary;
            if (card.querySelector('.rs-mc-character-lora').textContent !== loraText)
                card.querySelector('.rs-mc-character-lora').textContent = loraText;
            if (!on.checked) available = true;
        }
        const add = list.querySelector('.rs-mc-character-add');
        if (add.disabled === available) add.disabled = !available;
    }
    function closeCharacter(id) {
        const editor = editors.get(id);
        if (!editor || !editor.panel.classList.contains('is-open')) return;
        editor.panel.classList.remove('is-open');
        editor.panel.setAttribute('aria-hidden', 'true');
        editor.backdrop.hidden = true;
        syncCards(id);
        const fallback = document.querySelector(`.rs-mc-character-list[data-rs-target="${id}"] button:not([hidden])`);
        (editor.opener?.isConnected && editor.opener.getClientRects().length ? editor.opener : fallback)?.focus();
    }
    function openCharacter(id, slot, opener) {
        const editor = editors.get(id);
        const tab = editor?.panel.querySelectorAll('[role="tab"]')[slot];
        if (!editor || !tab) return;
        for (const other of editors.keys()) if (other !== id) closeCharacter(other);
        editor.opener = opener;
        editor.backdrop.hidden = false;
        editor.panel.classList.add('is-open');
        editor.panel.setAttribute('aria-hidden', 'false');
        document.getElementById(`rs_mc_editor_title_${id}`).textContent = `캐릭터 ${slot + 1} (프롬프트 입력)`;
        tab.click();
        // These are the original Gradio inputs: no shadow state or copying.
        requestAnimationFrame(() => {
            document.querySelector(`#rs_mc_prompt_${id}_${slot} textarea`)?.focus({preventScroll: true});
        });
    }
    function initCharacterEditor(id) {
        const panel = document.getElementById(`rs_mc_editor_${id}`);
        if (!panel || editors.get(id)?.panel === panel) return;
        const backdrop = document.createElement('div');
        backdrop.className = 'rs-mc-character-backdrop';
        backdrop.hidden = true;
        panel.before(backdrop);
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-modal', 'true');
        panel.setAttribute('aria-labelledby', `rs_mc_editor_title_${id}`);
        panel.setAttribute('aria-hidden', 'true');
        panel.classList.add('rs-mc-ui-ready');
        editors.set(id, {panel, backdrop, opener: null});
        document.getElementById(`rs_mc_enabled_${id}`)?.addEventListener('change', () => syncState(id));
        backdrop.onclick = () => closeCharacter(id);
        for (const button of panel.querySelectorAll('.rs-mc-character-close'))
            button.onclick = () => closeCharacter(id);
        // Gradio collapses the list in its own target handler, before this
        // panel's bubbling handler runs. Remember its state during capture.
        panel.addEventListener('keydown', event => {
            if (event.key === 'Escape' && panel.querySelector('input[aria-expanded="true"], .options[role="listbox"]'))
                event.rsDropdownWasOpen = true;
        }, {capture: true});
        panel.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                if (event.rsDropdownWasOpen) return;
                event.preventDefault(); event.stopPropagation(); closeCharacter(id);
            } else if (event.key === 'Tab') {
                const focusable = [...panel.querySelectorAll('button, input, textarea, select, [tabindex="0"]')]
                    .filter(element => !element.disabled && element.getClientRects().length);
                const first = focusable[0], last = focusable[focusable.length - 1];
                if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault(); last?.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault(); first?.focus();
                }
            }
        });
        panel.addEventListener('input', () => { syncCards(id); syncState(id); });
        panel.addEventListener('change', () => { syncCards(id); syncState(id); });
    }
    document.addEventListener('click', event => {
        const target = event.target instanceof Element ? event.target : event.target.parentElement;
        const opener = target.closest('.rs-mc-character-list [data-rs-slot], .rs-mc-preview [data-rs-slot]');
        if (opener) {
            const id = opener.closest('[data-rs-target]').dataset.rsTarget;
            openCharacter(id, Number(opener.dataset.rsSlot), opener);
        } else if (target.closest('.rs-mc-character-add')) {
            const button = target.closest('.rs-mc-character-add');
            const id = button.closest('[data-rs-target]').dataset.rsTarget;
            for (let slot = 0; slot < 10; slot++) {
                const input = document.querySelector(`#rs_mc_on_${id}_${slot} input`);
                if (input && !input.checked) {
                    input.click();
                    openCharacter(id, slot, button);
                    syncCards(id);
                    break;
                }
            }
        }
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const marker = event.target.closest?.('.rs-mc-preview [role="button"][data-rs-slot]');
        if (!marker) return;
        event.preventDefault();
        openCharacter(marker.closest('[data-rs-target]').dataset.rsTarget, Number(marker.dataset.rsSlot), marker);
    });
    function sceneField(id) { return document.querySelector(`#rs_mc_scene_${id} textarea`); }
    function writeScene(id, scene) {
        const input = sceneField(id);
        if (!input) throw Error('Cannot find RS scene input.');
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(input, JSON.stringify(scene));
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
    }
    async function openEditor(id) {
        const current = sceneField(id)?.value;
        const scene = current ? JSON.parse(current) : await (await fetch('/rs_mc_forge/default-scene')).json();
        const prefix = id === 't2i' ? 'txt2img' : 'img2img';
        const width = Number(document.querySelector(`#${prefix}_width input[type="number"]`)?.value) || 1024;
        const height = Number(document.querySelector(`#${prefix}_height input[type="number"]`)?.value) || 1024;
        const scale = Math.min(1, 2048 / Math.max(width, height));
        scene.width = Math.max(64, Math.round(width * scale));
        scene.height = Math.max(64, Math.round(height * scale));
        const token = crypto.randomUUID();
        const modal = document.createElement('dialog');
        modal.className = 'rs-mc-pose-dialog';
        const close = document.createElement('button'); close.textContent = '닫기 / Close'; close.type = 'button';
        const frame = document.createElement('iframe');
        // The original editor reads its message token from location.hash.
        frame.title = 'RS 3D Pose'; frame.src = `/rs_mc_forge/assets/web/pose3d/index.html?v=0.1.0a3#${token}`;
        modal.append(close, frame); document.body.append(modal);
        async function receive(event) {
            if (event.source !== frame.contentWindow || event.origin !== location.origin || event.data?.token !== token) return;
            if (event.data.type === 'rs-pose3d-ready') {
                frame.contentWindow.postMessage({type:'rs-pose3d-init',token,scene,locale:navigator.language,
                    host:'forge',outputSize:[width,height]}, location.origin);
            } else if (event.data.type === 'rs-pose3d-apply') {
                writeScene(id, event.data.scene);
            } else if (event.data.type === 'rs-pose3d-image-request') {
                const requestId=event.data.requestId;
                try {
                    const query=new URLSearchParams({character:String(event.data.person),scene:JSON.stringify(event.data.scene)});
                    const response=await fetch('/rs_mc_forge/image-pose?'+query,{method:'POST',body:event.data.file});
                    const data=await response.json();if(!response.ok)throw Error(data.error||'3D estimation failed.');
                    frame.contentWindow.postMessage({type:'rs-pose3d-image-result',token,requestId,...data},location.origin);
                } catch(error) {
                    frame.contentWindow.postMessage({type:'rs-pose3d-image-error',token,requestId,error:error.message},location.origin);
                }
            }
        }
        window.addEventListener('message', receive);
        modal.addEventListener('close', () => { window.removeEventListener('message',receive); modal.remove(); },{once:true});
        close.onclick = () => modal.close();
        modal.showModal();
    }
    onUiUpdate(() => {
        for (const id of ['t2i', 'i2i']) {
            initCharacterEditor(id);
            syncCards(id);
            syncState(id);
        }
        for (const button of document.querySelectorAll('button.rs-mc-pose-open:not([data-bound])')) {
            button.dataset.bound = '1';
            button.onclick = () => openEditor(button.dataset.rsTarget).catch(error => alert(error.message));
        }
    });
})();
