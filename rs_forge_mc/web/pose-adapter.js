/* SPDX-License-Identifier: GPL-3.0-only */
// Forge presentation adapter; the original editor and its bundle stay intact.
(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const footer = document.createElement('footer');
    footer.className = 'forge-pose-footer';
    footer.append($('apply'), $('status'));
    document.body.append(footer);
    const notice = document.createElement('p');
    notice.className = 'forge-pose-notice';
    $('image-drop').before(notice);
    $('image-drop').hidden = false;

    // Keep output size controlled by Forge, rather than silently creating a
    // mask with a different aspect ratio inside the embedded editor.
    $('width').readOnly = $('height').readOnly = true;
    function localize(locale) {
        const ko = locale.startsWith('ko');
        $('apply').textContent = ko ? '캐릭터 영역에 적용' : 'Apply to character regions';
        $('apply').dataset.i18n = 'forgeApply';
        notice.textContent = ko ? '한 명이 나온 이미지로 3D 자세를 추정합니다. 첫 사용 시 2.83 GB 가중치를 내려받습니다.'
            : 'Estimate one person, then edit the joints. First use downloads 2.83 GB weights.';
        $('width').title = $('height').title = ko ? 'Forge 출력 비율에 맞춘 편집 캔버스' : 'Editor canvas follows the Forge output ratio';
    }
    localize(navigator.language);
    window.addEventListener('message', event => {
        if (event.source !== parent || event.origin !== location.origin
            || event.data?.token !== location.hash.slice(1) || event.data.type !== 'rs-pose3d-init') return;
        // Run after the original editor's localization handler.
        queueMicrotask(() => localize(event.data.locale || navigator.language));
    });
    for (const id of ['library-status', 'status']) {
        const target = $(id);
        const observer = new MutationObserver(() => {
            const value = target.textContent.replaceAll('ComfyUI/models/rs_pose3d', 'Forge Neo/models/rs_pose3d')
                .replaceAll('노드에', '캐릭터 영역에').replaceAll('to node', 'to character regions');
            if (value !== target.textContent) target.textContent = value;
        });
        observer.observe(target, {childList:true, characterData:true, subtree:true});
    }
})();
