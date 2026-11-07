/* SPDX-License-Identifier: GPL-3.0-only */
(() => {
 'use strict';
 const get=(obj,path)=>path.split('.').reduce((a,k)=>a?.[k],obj);
 const set=(obj,path,value)=>{const keys=path.split('.');let cur=obj;for(const key of keys.slice(0,-1))cur=cur[key]??={};cur[keys.at(-1)]=value;};
 const input=id=>document.querySelector(`#rs_mc_features_${id} textarea`);
 const state=id=>JSON.parse(input(id)?.value||'{}');
 function write(id,value){const field=input(id);if(!field)throw Error('기능 설정 입력을 찾지 못했습니다.');field.value=JSON.stringify(value);updateInput(field);}
 function status(id,message){const target=document.querySelector(`.rs-mc-advanced[data-rs-target="${id}"] .rs-mc-advanced-status`);if(target)target.textContent=message;}
 function exportSettings(id){return new Promise((resolve,reject)=>{const cleanup=()=>{clearTimeout(timer);document.removeEventListener('rs-mc-exported',done);};const done=e=>{if(e.detail?.id!==id)return;cleanup();resolve(e.detail.value);};const timer=setTimeout(()=>{cleanup();reject(Error('설정 내보내기 응답을 받지 못했습니다.'));},30000);document.addEventListener('rs-mc-exported',done);document.querySelector(`#rs_mc_export_${id}`)?.click();});}
 async function request(url,options={}){const response=await fetch(`/rs_mc_forge/${url}`,options);const data=await response.json();if(!response.ok||data.error)throw Error(data.error||`요청 실패 (${response.status})`);return data;}
 function download(data,name){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);}
 const defaults=new WeakMap();
 function sync(id){let data;try{data=state(id);}catch{return;}
  for(const root of document.querySelectorAll(`[data-rs-target="${id}"]`))for(const control of root.querySelectorAll('[data-rs-feature]')){
   if(!defaults.has(control))defaults.set(control,control.type==='checkbox'?control.checked:control.value);
   const value=get(data,control.dataset.rsFeature)??defaults.get(control);
   if(control.type==='checkbox'){if(control.checked!==Boolean(value))control.checked=Boolean(value);}
   else if(control!==document.activeElement&&control.value!==String(value))control.value=String(value);
  }
  for(const row of document.querySelectorAll(`.rs-mc-extra[data-rs-target="${id}"]`)){
   const slot=row.querySelector('[data-rs-slot-status]')?.dataset.rsSlotStatus;
   const value=data.slots?.[slot]||{};
   const target=row.querySelector('[data-rs-slot-status]');
   const message=[value.mask?`마스크 ${value.mask.width}×${value.mask.height}`:'기본 영역',value.reference?`참조 이미지 ${value.reference.slice(0,8)}`:''].filter(Boolean).join(' · ');if(target&&target.textContent!==message)target.textContent=message;
  }
 }
 function maskDialog(id,slot){
  const dialog=document.createElement('dialog');dialog.className='rs-mc-mask-dialog';
  dialog.innerHTML='<h3>캐릭터 '+slot+' 영역 마스크</h3><p>흰색 영역에 이 캐릭터를 배치합니다. 마우스로 칠하거나 흑백 마스크를 가져오세요.</p><div class="rs-mc-feature-actions"><label>브러시 <input type="range" min="4" max="100" value="28"></label><label><input type="checkbox" class="erase">지우개</label><label class="rs-mc-upload">마스크 가져오기<input type="file" accept="image/*"></label><button type="button" class="clear">전체 지우기</button></div><canvas width="512" height="512" aria-label="영역 마스크 그리기"></canvas><p role="status"></p><div class="rs-mc-feature-actions"><button type="button" class="save">이 마스크 적용</button><button type="button" class="cancel">취소</button></div>';
  const canvas=dialog.querySelector('canvas'),ctx=canvas.getContext('2d',{willReadFrequently:true});
  const width=+(document.querySelector(`#${id==='t2i'?'txt2img':'img2img'}_width input[type=number]`)?.value||1024),height=+(document.querySelector(`#${id==='t2i'?'txt2img':'img2img'}_height input[type=number]`)?.value||1024);
  canvas.width=Math.max(64,Math.round(512*Math.min(1,width/height)));canvas.height=Math.max(64,Math.round(512*Math.min(1,height/width)));
  ctx.fillStyle='#000';ctx.fillRect(0,0,canvas.width,canvas.height);
  const existing=state(id).slots?.[slot]?.mask;
  if(existing){const packed=Uint8Array.from(atob(existing.bits),c=>c.charCodeAt(0));const temp=document.createElement('canvas');temp.width=existing.width;temp.height=existing.height;const tc=temp.getContext('2d'),pixels=tc.createImageData(temp.width,temp.height);for(let i=0;i<temp.width*temp.height;i++){const v=(packed[i>>3]>>(7-i%8)&1)*255;pixels.data.set([v,v,v,255],i*4);}tc.putImageData(pixels,0,0);ctx.drawImage(temp,0,0,canvas.width,canvas.height);}
  let down=false,last;
  const point=e=>{const b=canvas.getBoundingClientRect();return [(e.clientX-b.left)*canvas.width/b.width,(e.clientY-b.top)*canvas.height/b.height];};
  function paint(e){const p=point(e);ctx.strokeStyle=dialog.querySelector('.erase').checked?'#000':'#fff';ctx.lineWidth=+dialog.querySelector('input[type=range]').value;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(...(last||p));ctx.lineTo(...p);ctx.stroke();last=p;}
  canvas.onpointerdown=e=>{down=true;last=null;canvas.setPointerCapture(e.pointerId);paint(e);};canvas.onpointermove=e=>{if(down)paint(e);};canvas.onpointerup=canvas.onpointercancel=()=>{down=false;last=null;};
  dialog.querySelector('.clear').onclick=()=>{ctx.fillStyle='#000';ctx.fillRect(0,0,canvas.width,canvas.height);};
  dialog.querySelector('input[type=file]').onchange=async e=>{const file=e.target.files[0];if(!file)return;const bitmap=await createImageBitmap(file);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();};
  dialog.querySelector('.save').onclick=()=>{const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;const bits=new Uint8Array(Math.ceil(pixels.length/32));let filled=0;for(let i=0;i<pixels.length/4;i++)if(pixels[4*i]>127&&pixels[4*i+3]>127){bits[i>>3]|=1<<(7-i%8);filled++;}if(!filled){dialog.querySelector('[role=status]').textContent='영역을 먼저 칠해 주세요.';return;}const data=state(id);set(data,`slots.${slot}.mask`,{width:canvas.width,height:canvas.height,bits:btoa(String.fromCharCode(...bits))});write(id,data);dialog.close();};
  dialog.querySelector('.cancel').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();
 }
 async function bind(root){
  if(root.dataset.rsFeaturesBound)return;root.dataset.rsFeaturesBound='1';const id=root.dataset.rsTarget;
  for(const control of root.querySelectorAll('[data-rs-feature]'))control.addEventListener('change',()=>{try{const data=state(id);set(data,control.dataset.rsFeature,control.type==='checkbox'?control.checked:control.type==='number'?Number(control.value):control.value);write(id,data);status(id,'설정 저장됨');}catch(error){status(id,error.message);}});
  for(const button of root.querySelectorAll('[data-rs-mask]'))button.onclick=()=>maskDialog(id,button.dataset.rsMask);
  for(const button of root.querySelectorAll('[data-rs-tag-reference]'))button.onclick=async()=>{button.disabled=true;const target=root.querySelector('[data-rs-tag-result]');try{const data=state(id),asset=data.slots?.[button.dataset.rsTagReference]?.reference;if(!asset)throw Error('참조 이미지를 먼저 넣어 주세요.');target.textContent='태그 분석 중… CPU 처리에 시간이 걸릴 수 있습니다.';const response=await fetch('/rs_mc_forge/reference/'+asset);if(!response.ok)throw Error('참조 이미지를 다시 업로드해 주세요.');const model=data.detailer?.tagger||'WD ViT v3';const result=await request('tag?model='+encodeURIComponent(model),{method:'POST',body:await response.blob()});target.textContent=Object.entries(result.tags).sort((a,b)=>b[1]-a[1]).slice(0,60).map(([name,score])=>`${name} (${score.toFixed(2)})`).join(', ');}catch(error){target.textContent=error.message;}finally{button.disabled=false;}};
  for(const [selector,key,attr] of [['[data-rs-mask-clear]','mask','rsMaskClear'],['[data-rs-reference-clear]','reference','rsReferenceClear']])for(const button of root.querySelectorAll(selector))button.onclick=()=>{const data=state(id);if(data.slots?.[button.dataset[attr]])delete data.slots[button.dataset[attr]][key];write(id,data);};
  for(const upload of root.querySelectorAll('input[type=file]'))upload.onchange=async()=>{
   const file=upload.files[0];if(!file)return;upload.disabled=true;status(id,'처리 중…');
   try{
    if(upload.hasAttribute('data-rs-reference')){const result=await request('reference',{method:'POST',body:file});const data=state(id);set(data,`slots.${upload.dataset.rsReference}.reference`,result.asset);write(id,data);}
    else if(upload.hasAttribute('data-rs-openpose')){const result=await request('openpose?filename='+encodeURIComponent(file.name),{method:'POST',body:file});const data=state(id);data.openpose=result;write(id,data);}
    else if(upload.hasAttribute('data-rs-metadata')){const result=await request('import-settings?filename='+encodeURIComponent(file.name),{method:'POST',body:file});const field=document.querySelector(`#rs_mc_preset_${id} textarea`);if(!field)throw Error('프리셋 가져오기 입력을 찾지 못했습니다.');field.value=JSON.stringify(result);updateInput(field);document.querySelector(`#rs_mc_import_${id}`)?.click();}
    status(id,'가져오기 완료');
   }catch(error){status(id,error.message);}finally{upload.disabled=false;upload.value='';}
  };
  const clear=root.querySelector('[data-rs-openpose-clear]');if(clear)clear.onclick=()=>{const data=state(id);delete data.openpose;write(id,data);};
  const exportNai=root.querySelector('[data-rs-nai-export]');if(exportNai)exportNai.onclick=async()=>{try{download(await request('nai-export',{method:'POST',body:JSON.stringify({config:JSON.parse(await exportSettings(id)),prompt:document.querySelector(`#${id==='t2i'?'txt2img':'img2img'}_prompt textarea`)?.value||'',negative:document.querySelector(`#${id==='t2i'?'txt2img':'img2img'}_neg_prompt textarea`)?.value||''})}),'rs-nai-characters.json');}catch(e){status(id,e.message);}};
  const batch=root.querySelector('[data-rs-folder-run]');if(batch)batch.onclick=async()=>{batch.disabled=true;try{const tab=id==='t2i'?'txt2img':'img2img';const value=(suffix,selector='input')=>document.querySelector(`#${tab}_${suffix} ${selector}`)?.value;const data={config:JSON.parse(await exportSettings(id)),source:root.querySelector('[data-rs-folder-source]').value,output:root.querySelector('[data-rs-folder-output]').value,prompt:value('prompt','textarea')||'',negative:value('neg_prompt','textarea')||'',seed:Number(value('seed')||0),sampler:value('sampling')||'Euler a',scheduler:value('scheduler')||'SGM Uniform'};status(id,'폴더 보정 중… 다른 생성 작업이 있으면 끝날 때까지 기다립니다.');const result=await request('detail-folder',{method:'POST',body:JSON.stringify(data)});status(id,`${result.images.length}장 저장 완료: ${result.output}`);}catch(e){status(id,e.message);}finally{batch.disabled=false;}};
  if(root.classList.contains('rs-mc-advanced'))try{const choices=await request('detectors');for(const kind of ['segm','bbox','sam']){const select=root.querySelector(`[data-rs-feature="detailer.${kind}"]`);for(const value of choices[kind].slice(1)){const option=document.createElement('option');option.value=option.textContent=value;select.append(option);}}sync(id);}catch(e){status(id,e.message);}
 }
 onUiUpdate(()=>{for(const root of document.querySelectorAll('.rs-mc-extra[data-rs-target],.rs-mc-advanced[data-rs-target]'))bind(root);for(const id of ['t2i','i2i'])sync(id);});
})();
