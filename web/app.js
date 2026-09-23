/* MeetNotes SPA —— 原生 JS，无依赖 */
const $app = document.getElementById('app');
const $toast = document.getElementById('toast');
let pollTimer = null, recState = null;

/* ---------- 工具 ---------- */
function toast(msg){ $toast.textContent = msg; $toast.classList.add('show');
  clearTimeout(toast._t); toast._t = setTimeout(()=> $toast.classList.remove('show'), 2200); }

async function api(path, opt={}){
  const r = await fetch(path, opt);
  if(!r.ok){ let msg; try{ msg=(await r.json()).detail }catch(e){ msg=r.statusText }
    throw new Error(msg || `HTTP ${r.status}`); }
  return r.status===200 ? r.json() : null;
}

const STATUS_TEXT = {queued:'排队中', processing:'处理中', done:'已完成', failed:'失败'};
const STEP_TEXT = {normalizing:'音频预处理', transcribing:'语音转写', polishing:'文稿整理', summarizing:'生成摘要',
                   uploaded:'已上传', transcribed:'转写完成', polished_done:'整理完成', summary_done:'摘要完成'};

function esc(s){ const d=document.createElement('div'); d.textContent=s??''; return d.innerHTML; }

/* markdown 简版渲染：##/###、列表、- [ ]、**粗体**、[MM:SS] 锚点 */
function md2html(md){
  const lines = String(md||'').replace(/\r/g,'').split('\n');
  const out=[];
  const inline = s => esc(s)
      .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
      .replace(/[（(]?(\d{1,2}:\d{2}(?::\d{2})?)[)）]?/g,(m,t)=>`<span class="ts-chip" data-t="${t}">▶ ${t}</span>`)
      .replace(/(?<!\()\[(\d{1,2}:\d{2}(?::\d{2})?)\](?!\))/g,(m,t)=>`<span class="ts-chip" data-t="${t}">▶ ${t}</span>`);
  for(const raw of lines){
    const line = raw.trimEnd();
    let m;
    if(m=line.match(/^#{1,3}\s+(.*)/)) out.push(`<h3>${inline(m[1])}</h3>`);
    else if(m=line.match(/^\s*-\s*\[\s\]\s*(.*)/)) out.push(`<li class="todo">${inline('☐ '+m[1])}</li>`);
    else if(m=line.match(/^\s*-\s*\[x\]\s*(.*)/i)) out.push(`<li>${inline('☑ '+m[1])}</li>`);
    else if(m=line.match(/^\s*[-*]\s+(.*)/)) out.push(`<li>${inline(m[1])}</li>`);
    else if(line.trim()==='') out.push('');
    else out.push(`<p>${inline(line)}</p>`);
  }
  // 相邻 li 合并为 ul
  return out.join('\n').replace(/(<li[^>]*>[\s\S]*?<\/li>)(\n<li)/g,'$1$2')
                      .replace(/^((?:<li.*<\/li>\n?)+)$/gm,'<ul>$1</ul>');
}

function tsToSec(t){ const p=t.split(':').map(Number);
  return p.length===3 ? p[0]*3600+p[1]*60+p[2] : p[0]*60+p[1]; }

function fmtDur(s){ s=Math.round(s); const m=Math.floor(s/60), sec=s%60;
  const h=Math.floor(m/60); return h? `${h}小时${m%60}分`: `${m}分${sec?sec+'秒':''}`||'—'; }

/* ---------- 顶部导航 ---------- */
function setNav(name){
  document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active', a.dataset.nav===name));
}

/* ---------- 列表页 ---------- */
async function renderList(){
  setNav('list'); stopPoll();
  $app.innerHTML = `
    <div class="dropzone" id="dropzone">
      <div class="big">📤</div>
      <div><b>拖拽录音文件到这里，或点击选择文件</b></div>
      <p>支持 mp3 / wav / m4a / webm / aac / flac / ogg / amr 等 · 转录与摘要在云端自动完成</p>
      <input type="file" id="fileInput" multiple hidden accept="audio/*,.amr,.opus">
    </div>
    <div style="text-align:center;margin:-8px 0 4px"><button class="btn-rec" id="btnRec">🎙️ 开始页面录音</button></div>
    <div class="list-head"><h2>全部会议</h2>
      <select id="projFilter" class="proj-filter"></select></div>
    <div class="proj-assign" id="projAssign"></div>
    <div class="meet-list" id="meetList"></div>`;
  bindUpload(); bindRec(); await refreshList(true);

  const dz=document.getElementById('dropzone');
  dz.ondragover=e=>{e.preventDefault();dz.classList.add('over')};
  dz.ondragleave=()=>dz.classList.remove('over');
  dz.ondrop=e=>{e.preventDefault();dz.classList.remove('over');uploadFiles(e.dataTransfer.files)};
}

let curProjectFilter='';   // ''=全部 | 项目名 | '__none__'
async function refreshList(poll=false){
  try{
    const list = await api('/api/meetings');
    const el = document.getElementById('meetList'); if(!el) return;
    const groups={};
    for(const m of list){ const p=m.project||''; (groups[p]=groups[p]||[]).push(m) }
    el.innerHTML='';
    const named=Object.keys(groups).filter(k=>k).sort((a,b)=>{
      const ca=groups[a].length, cb=groups[b].length; return cb-ca||a.localeCompare(b) });
    if(!list.length) el.innerHTML=`<div class="empty">还没有会议记录，上传一段录音开始吧</div>`;
    const drawRows=(rows)=>{
      for(const m of rows){
        const d=document.createElement('div'); d.className='mrow'; d.draggable=true;
        d.ondragstart=e=>{ e.dataTransfer.setData('text/meetid', m.id); e.dataTransfer.effectAllowed='move'; };
        d.innerHTML = `
        <div class="m-main"><div class="m-title">${esc(m.title)}</div>
          <div class="m-sub">${esc(m.created_at)}${m.duration?` · ${fmtDur(m.duration)}`:''}</div></div>
        ${badgeHtml(m)} <button class="del-btn" title="删除">✕</button>`;
        d.onclick=()=>location.hash=`#/m/${m.id}`;
        d.querySelector('.del-btn').onclick=async e=>{ e.stopPropagation();
          if(confirm(`删除会议「${m.title}」？音频和纪要将一并删除`)){
            await api(`/api/meetings/${m.id}`,{method:'DELETE'}); refreshList(); }};
        el.appendChild(d);
      }
    };
    const foldKey=(n)=>n||'__none__';
    const getFolded=()=>{ try{ return JSON.parse(localStorage.getItem('mn_folded')||'[]') }catch{ return [] } };
    const setFolded=(arr)=>localStorage.setItem('mn_folded', JSON.stringify(arr));
    const drawGroup=(name, rows)=>{
      const folded=getFolded().includes(foldKey(name));
      const g=document.createElement('div'); g.className='proj-group'; g.dataset.proj=name||'__none__';
      g.innerHTML=`<div class="proj-head ${folded?'folded':''}">
          <span class="proj-arrow">${folded?'▸':'▾'}</span>
          <span class="proj-name">📁 ${esc(name||'未分组')}</span>
          <span class="proj-count">${rows.length} 场</span>
          ${name?`<span class="proj-ops">
            <button class="proj-btn" data-op="rename" title="重命名项目">✏️</button>
            <button class="proj-btn" data-op="dissolve" title="解散分组（会议保留）">✕</button></span>`:''}
        </div>`;
      // 折叠/展开（点头切换）
      g.querySelector('.proj-head').onclick=e=>{
        if(e.target.closest('.proj-btn')) return;
        const arr=getFolded(); const k=foldKey(name);
        const i=arr.indexOf(k);
        if(i>=0) arr.splice(i,1); else arr.push(k);
        setFolded(arr); renderList();
      };
      if(name){
        g.querySelector('[data-op=rename]').onclick=async e=>{ e.stopPropagation();
          const nn=prompt('新项目名称：', name); if(!nn||nn.trim()===name) return;
          await api(`/api/projects/${encodeURIComponent(name)}`,{method:'PATCH',
            headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nn.trim()})});
          if(curProjectFilter===name) curProjectFilter=nn.trim();
          renderList(); };
        g.querySelector('[data-op=dissolve]').onclick=async e=>{ e.stopPropagation();
          if(confirm(`解散项目「${name}」？组内 ${rows.length} 场会议将移入未分组`)){
            await api(`/api/projects/${encodeURIComponent(name)}`,{method:'DELETE'});
            curProjectFilter=''; renderList(); }};
      }
      // 拖拽移动会议到该组
      g.ondragover=e=>{ e.preventDefault(); g.classList.add('drag-over') };
      g.ondragleave=e=>{ if(!g.contains(e.relatedTarget)) g.classList.remove('drag-over') };
      g.ondrop=async e=>{
        e.preventDefault(); g.classList.remove('drag-over');
        const mid=e.dataTransfer.getData('text/meetid'); if(!mid) return;
        const m=list.find(x=>x.id===mid); if(!m) return;
        if((m.project||'')===(name||'')) return;
        await api(`/api/meetings/${mid}`,{method:'PATCH',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({project:name||''})});
        toast(`「${m.title}」已移至 ${name||'未分组'}`);
        renderList();
      };
      el.appendChild(g);
      if(!folded) drawRows(rows);
      else { const tip=document.createElement('div'); tip.className='fold-tip';
        tip.textContent=`已折叠 ${rows.length} 场会议`; el.appendChild(tip); }
    };
    if(list.length){
      if(curProjectFilter==='__none__'){ if(groups['']) drawGroup('', groups['']) }
      else if(curProjectFilter){ if(groups[curProjectFilter]) drawGroup(curProjectFilter, groups[curProjectFilter]) }
      else { named.forEach(n=>drawGroup(n, groups[n]));
             if(groups['']) drawGroup('', groups['']) }
    }
    // 项目筛选器
    const sel=document.getElementById('projFilter');
    if(sel){
      sel.innerHTML=`<option value="">全部会议 (${list.length})</option>`+
        named.map(n=>`<option value="${esc(n)}" ${curProjectFilter===n?'selected':''}>📁 ${esc(n)} (${groups[n].length})</option>`).join('')+
        (groups['']?`<option value="__none__" ${curProjectFilter==='__none__'?'selected':''}>未分组 (${groups[''].length})</option>`:'');
      sel.onchange=()=>{ curProjectFilter=sel.value; renderList() };
    }
    // 上传归组选择器
    const pa=document.getElementById('projAssign');
    if(pa){
      const saved=localStorage.getItem('mn_proj')||'';
      pa.innerHTML=`<span class="pa-label">新会议归入：</span>
        <select id="paSel" class="pa-sel"><option value="">未分组</option>${
          named.map(n=>`<option value="${esc(n)}" ${saved===n?'selected':''}>📁 ${esc(n)}</option>`).join('')}</select>
        <button class="proj-btn pa-new">＋ 新建项目</button>`;
      document.getElementById('paSel').onchange=e=>localStorage.setItem('mn_proj',e.target.value);
      pa.querySelector('.pa-new').onclick=()=>{
        const nn=prompt('新项目名称：'); if(!nn||!nn.trim()) return;
        localStorage.setItem('mn_proj', nn.trim()); renderList(); };
    }
    if(list.some(m=>['queued','processing'].includes(m.status))) startPoll(()=>refreshList(true), 4000);
    else stopPoll();
  }catch(e){ console.warn(e) }
}

function badgeHtml(m){
  if(m.status==='processing') return `<span class="badge processing"><span class="spin"></span> ${STEP_TEXT[m.step]||'处理中'}</span>`;
  if(m.status==='failed') return `<span class="badge failed">失败</span>`;
  if(m.status==='done') return `<span class="badge done">✓ 已完成</span>`;
  return `<span class="badge queued">排队中</span>`;
}

/* ---------- 上传 & 录音 ---------- */
function bindUpload(){
  const dz=document.getElementById('dropzone'), fi=document.getElementById('fileInput');
  dz.onclick=()=>fi.click();
  fi.onchange=()=>uploadFiles(fi.files);
}
async function uploadFiles(files){
  for(const f of files){
    const fd=new FormData(); fd.append('file', f);
    const pj=localStorage.getItem('mn_proj'); if(pj) fd.append('project', pj);
    try{
      const r=await api('/api/meetings',{method:'POST',body:fd});
      toast(`已上传：「${f.name}」，开始转录`);
      location.hash=`#/m/${r.id}`;
    }catch(e){ alert(`「${f.name}」上传失败：${e.message}`) }
  }
}
function bindRec(){
  const btn=document.getElementById('btnRec');
  btn.onclick=async()=>{
    if(recState){ mediaStop(); return }
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:true});
      const rec=new MediaRecorder(stream);
      const chunks=[]; rec.ondataavailable=e=>chunks.push(e.data);
      rec.onstop=async()=>{
        stream.getTracks().forEach(t=>t.stop());
        const blob=new Blob(chunks,{type:rec.mimeType});
        const name=`现场录音 ${new Date().toLocaleString('zh-CN',{hour12:false}).slice(5,16).replace('/','-')}`;
        const fd=new FormData(); fd.append('file', blob, `${name}.webm`);
        const pj=localStorage.getItem('mn_proj'); if(pj) fd.append('project', pj);
        btn.textContent='⬆️ 上传中…'; 
        try{ const r=await api('/api/meetings',{method:'POST',body:fd});
             toast('录音已保存并开始转录'); location.hash=`#/m/${r.id}`; }
        catch(e){ alert(`录音上传失败：${e.message}`); resetRecBtn() }
      };
      rec.start(); recState={rec};
      btn.classList.add('recording'); 
      let sec=0; btn.innerHTML='<span class="rec-dot"></span> 录音中 00:00（点击停止）';
      recState.timer=setInterval(()=>{ sec++; btn.innerHTML=
        `<span class="rec-dot"></span> 录音中 ${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}（点击停止）`},1000);
    }catch(e){ alert('无法访问麦克风：'+e.message) }
  };
}
function mediaStop(){ clearInterval(recState?.timer); recState?.rec.stop(); recState=null }
function resetRecBtn(){ const b=document.getElementById('btnRec');
  if(b){ b.classList.remove('recording'); b.textContent='🎙️ 开始页面录音' } }

/* ---------- 详情页 ---------- */
let curDetail=null, curTab='polished';

async function renderDetail(mid){
  setNav('list'); stopPoll();
  $app.innerHTML=`<div id="dWrap">加载中…</div>`;
  try{ curDetail=await api(`/api/meetings/${mid}`) }catch(e){ $app.innerHTML=`会议不存在`; return }
  paintDetail(curDetail);
  if(['queued','processing','failed'].includes(curDetail.status)) startPoll(refreshDetail, 2500);
}

async function refreshDetail(){
  if(!curDetail) return;
  const old=curDetail; curDetail=await api(`/api/meetings/${curDetail.id}`);
  if(location.hash!==`#/m/${old.id}`){ stopPoll(); return }
  if(JSON.stringify(old)!==JSON.stringify({...curDetail,_:undefined})) {
    paintDetail(curDetail);
    if(['done','failed'].includes(curDetail.status)){ stopPoll(); setTimeout(refreshDetailOnceSafe,300) }
    else if(curDetail.status==='processing'||curDetail.status==='queued') startPoll(refreshDetail,2500);
  }
}
async function refreshDetailOnceSafe(){ /* 收尾再拉一次确保最新 artifacts */ }

function paintDetail(m){
  $app.querySelector('#dWrap').innerHTML=`
    <div class="detail-shell">
      <div class="detail-head"><a href="#/" class="back-link">← 返回会议列表</a></div>
      <div class="detail-grid">
        <aside class="detail-side">
          <div class="side-card">
        <div class="m-title" id="mTitle">${esc(m.title)}<button class="title-edit" id="titleEdit" title="重命名">✏️</button></div>
        <div class="meta-line"><span>状态</span>${statusBadgeInline(m)}</div>
        <div class="meta-line"><span>时长</span><span>${m.duration?fmtDur(m.duration):'解析中'}</span></div>
        <div class="meta-line"><span>创建时间</span><span>${esc(m.created_at)}</span></div>
        <div class="meta-line"><span>项目</span><span id="projVal">${esc(m.project||'未分组')}</span><button class="title-edit" id="projEdit" title="设置项目">✏️</button></div>
        <div class="steps">
          ${stepRow('transcribing','语音转写',m)}
          ${stepRow('polishing','文稿整理',m)}
          ${stepRow('summarizing','摘要 / 待办',m)}
        </div>
        ${m.error?`<div class="err-box">⚠️ ${esc(m.error)}</div>`:''}
          </div>
        </aside>
        <section class="detail-main">
          <div class="tabs">
            <button class="tab ${curTab==='polished'?'active':''}" data-tab="polished">✍️ 整理稿</button>
            <button class="tab ${curTab==='summary'?'active':''}" data-tab="summary">📋 摘要与待办</button>
            <button class="tab ${curTab==='transcript'?'active':''}" data-tab="transcript">原始转写</button>
          </div>
          <div class="doc-card" id="tabBody"></div>
        </section>
      </div>
      <div class="detail-footer">${
        m.audio_file ? `<span class="df-label">🔊 回放</span><audio id="player" controls src="/audio/${esc(m.audio_file)}"></audio>`
                     : `<div class="no-audio">${['done','failed'].includes(m.status)?'音频不可用':'音频处理中…'}</div>`}
      </div>
    </div>`;
  $app.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{ curTab=t.dataset.tab; editing=false; paintTabsOnly() });
  bindTitleEdit(m);
  bindTsClicks(); paintTabsOnly();
  const p=document.getElementById('player');
  if(p && p.dataset.bind!=='1'){ p.dataset.bind='1'; p.addEventListener('timeupdate',onTimeUpdate) }
}
function statusBadgeInline(m){ return badgeHtml(m).replace('class="badge','style="margin-left:auto" class="badge') }

function bindTitleEdit(m){
  const btn=$app.querySelector('#titleEdit'); if(!btn) return;
  const pe=$app.querySelector('#projEdit'); if(pe) pe.onclick=async()=>{
    const projects=(await api('/api/projects')).map(p=>p.name);
    const cur=m.project||'';
    const nn=prompt(`设置项目名称（现有: ${projects.join('、')||'无'}；留空=未分组）：`, cur);
    if(nn===null) return;
    const v=nn.trim();
    if(v===cur) return;
    await api(`/api/meetings/${m.id}`,{method:'PATCH',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({project:v})});
    curDetail.project=v; toast('✅ 项目已更新'); paintDetail(curDetail);
  };
  btn.onclick=()=>{
    const wrap=$app.querySelector('#mTitle');
    wrap.classList.add('editing');
    wrap.innerHTML=`<input id="titleInput" class="title-input" value="${esc(m.title)}" maxlength="80">
      <button class="step-run" id="titleSave">保存</button><button class="step-run" id="titleCancel">取消</button>`;
    const input=$app.querySelector('#titleInput');
    input.focus(); input.select();
    $app.querySelector('#titleCancel').onclick=()=>paintDetail(curDetail);
    const save=async()=>{
      const v=input.value.trim();
      if(!v){ toast('标题不能为空'); return }
      try{ await api(`/api/meetings/${m.id}`,{method:'PATCH',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({title:v})});
        curDetail.title=v; toast('✅ 已重命名'); paintDetail(curDetail);
      }catch(e){ alert('保存失败：'+e.message) }
    };
    $app.querySelector('#titleSave').onclick=save;
    input.onkeydown=e=>{ if(e.key==='Enter')save(); if(e.key==='Escape')paintDetail(curDetail) };
  };
}
function stepRow(key,label,m){
  const busy = m.status==='processing' &&
      ({transcribing:'transcribing',polishing:'polishing',summarizing:'summarizing'})[key]===m.step;
  const has = key==='transcribing'? (m.segments?.length>0)
            : key==='polishing'? !!m.polished : !!m.summary;
  return `<div class="step-row"><span>${busy?'⏳':has?'✅':'·'} ${label}</span>
    ${m.status==='done'||m.status==='failed'?`<button class="step-run" data-retry="${key}">重跑</button>`:''}</div>`;
}

let editing=false;
function paintTabsOnly(){ 
  const body=$app.querySelector('#tabBody'); if(!body) return;
  $app.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active', t.dataset.tab===curTab));
  const m=curDetail;
  if(editing){
    const kind=curTab==='polished'?'polished':'summary';
    const raw=(kind==='polished'? m.polished?.content : m.summary?.content)||'';
    body.classList.add('editing');
    body.innerHTML=`<textarea class="edit-area" id="editArea" spellcheck="false">${esc(raw)}</textarea>
      <div class="action-bar"><span class="edit-hint">编辑模式 · ${kind==='polished'?'整理稿':'摘要'} · Ctrl+Enter 保存</span>
      <button class="act-btn" id="cancelEdit"><span class="ic">↩</span>取消</button>
      <button class="act-btn primary" id="saveEdit"><span class="ic">✓</span>保存修改</button></div>`;
    const saveEdit=async()=>{
      try{ await api(`/api/meetings/${m.id}/artifact/${kind}`,{method:'PATCH',
           headers:{'Content-Type':'application/json'},body:JSON.stringify({content:body.querySelector('#editArea').value})});
        editing=false; if(kind==='polished'&&m.polished)m.polished.content=body.querySelector('#editArea').value;
        else if(m.summary)m.summary.content=body.querySelector('#editArea').value;
        toast('已保存'); paintTabsOnly();
      }catch(e){alert('保存失败：'+e.message)}
    };
    body.querySelector('#cancelEdit').onclick=()=>{editing=false;paintTabsOnly()};
    body.querySelector('#saveEdit').onclick=saveEdit;
    body.querySelector('#editArea').onkeydown=e=>{
      if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)) saveEdit();
      if(e.key==='Escape'){editing=false;paintTabsOnly()}};
    return;
  }
  body.classList.remove('editing');
  if(curTab==='transcript'){
    const segs=m.segments||[];
    body.innerHTML= segs.length
      ? `<div id="segList">${segs.map(s=>`
          <div class="seg-row" data-start="${s.t_start}">
            <span class="seg-ts">${tsShort(s.t_start)}</span><span>${esc(s.text)}</span></div>`).join('')}</div>`
      : `<div class="empty">${m.status==='processing'?'转写进行中…':'暂无内容'}</div>`;
    body.querySelectorAll('.seg-row').forEach(r=>r.onclick=()=>seekTo(+r.dataset.start));
  }else{
    const art=curTab==='polished'?m.polished:m.summary;
    const statusNote = !art
      ? `<div class="empty">${m.status==='processing'?(curTab==='polished'?'正在整理文稿…':'正在生成摘要…'):(curTab==='failed'?'处理失败，可从左侧重跑对应步骤':'暂未生成')}</div>`
      : '';
    body.innerHTML=`<div class="doc-body md-render">${art?md2html(art.content):''}</div>${statusNote}
      ${art?`<div class="action-bar"><button class="act-btn" id="editBtn"><span class="ic">✏️</span>编辑原文</button>
             <button class="act-btn" id="exportBtn"><span class="ic">⬇️</span>导出 Markdown</button></div>`:''}`;
    const eb=body.querySelector('#editBtn'); if(eb) eb.onclick=()=>{editing=true;paintTabsOnly()};
    const xb=body.querySelector('#exportBtn'); if(xb) xb.onclick=()=>{
      const blob=new Blob([art.content],{type:'text/markdown'});
      const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
      a.download=`${m.title}_${curTab==='polished'?'整理稿':'摘要'}.md`; a.click();
    };
    body.classList.toggle('md-render',true); bindTsClicks(body);
  }
}
function tsShort(sec){ const s=Math.floor(sec); const m=Math.floor(s/60),ss=s%60,h=Math.floor(m/60);
  return h?`${h}:${String(m%60).padStart(2,'0')}:${String(ss).padStart(2,'0')}`:`${m}:${String(ss).padStart(2,'0')}` }
function seekTo(sec){ const p=document.getElementById('player'); if(!p) return; p.currentTime=sec; p.play().catch(()=>{}) }
function bindTsClicks(root=$app){
  root.querySelectorAll('.ts-chip').forEach(c=>{
    c.onclick=e=>{ e.stopPropagation(); seekTo(tsToSec(c.dataset.t.replace(/：/g,':'))) } });
  root.querySelectorAll('.seg-row').forEach(r=>{
    if(!r.dataset.bound){ r.dataset.bound='1';
      r.onclick=()=>seekTo(+r.dataset.start) } });
}
function onTimeUpdate(){
  const p=document.getElementById('player'); if(!p||curTab!=='transcript') return;
  const rows=$app.querySelectorAll('.seg-row'); let active=null;
  rows.forEach(r=>{ const st=+r.dataset.start;
    if(st<=p.currentTime+0.15){ if(active===null||st>+active.dataset.start) active=r } });
  rows.forEach(r=>r.classList.remove('playing'));
  if(active){ active.classList.add('playing');
    const box=document.getElementById('segList');
    if(box && Math.abs((box._lastActive??-999)-+active.dataset.start)>60)
      { active.scrollIntoView({block:'center',behavior:'smooth'}); box._lastActive=+active.dataset.start } }
}

$app.addEventListener('click', async e=>{
  const b=e.target.closest('[data-retry]'); if(!b) return;
  b.disabled=true; b.textContent='…';
  try{ await api(`/api/meetings/${curDetail.id}/retry`,{method:'POST',
       headers:{'Content-Type':'application/json'},body:JSON.stringify({step:b.dataset.retry})});
    toast('已重新提交任务'); refreshDetail();
  }catch(err){ alert(err.message); b.disabled=false }
});

/* ---------- 设置弹窗 ---------- */
function ensureModal(){
  if(document.getElementById('modalMask')) return;
  const mask=document.createElement('div'); mask.id='modalMask';
  mask.innerHTML=`<div class="modal-card" id="modalCard"></div>`;
  mask.onclick=e=>{ if(e.target===mask) closeSettings() };
  document.body.appendChild(mask);
}
function closeSettings(){
  document.getElementById('modalMask')?.remove();
  document.removeEventListener('keydown', escSettings);
}
function escSettings(e){ if(e.key==='Escape') closeSettings() }

async function openSettings(){
  ensureModal();
  const s=await api('/api/settings');
  const card=document.getElementById('modalCard');
  card.innerHTML=`
   <div class="modal-head"><h2>⚙️ 全局设置</h2><button class="modal-close" id="modalClose">✕</button></div>
   <div class="modal-body">
   <p class="set-desc">所有配置保存在本机 data/config.json，修改即时生效。</p>
     <div class="grid2">
       <div class="field"><label>转录引擎</label>
         <select id="f-transcriber">
           <option value="ark" ${s.transcriber==='ark'?'selected':''}>火山方舟（云 · 推荐）</option>
           <option value="whisper-local" ${s.transcriber==='whisper-local'?'selected':''}>本地 Whisper${s.whisper_local_available?'':'（未安装）'}</option>
         </select>
         <div class="hint">本地引擎需先执行 pip install faster-whisper</div>
       </div>
       <div class="field"><label>方舟 Base URL（ASR）</label>
         <input id="f-asr-url" value="${esc(s.asr.base_url)}"></div>
       <div class="field"><label>方舟 API Key（ASR）</label>
         <input id="f-asr-key" type="password" placeholder="${esc(s.asr.api_key_hint||'尚未设置')}" onfocus="this.placeholder=''"></div>
       <div class="field"><label>ASR 模型</label>
         <input id="f-asr-model" value="${esc(s.asr.model)}"></div>
       <div class="field"><label>文本 Base URL（润色/摘要）</label>
         <input id="f-llm-url" value="${esc(s.llm.base_url)}">
         <div class="hint">DeepSeek 官方：https://api.deepseek.com ｜ 方舟：https://ark.cn-beijing.volces.com/api/v3</div>
       </div>
       <div class="field"><label>文本 API Key</label>
         <input id="f-llm-key" type="password" placeholder="${esc(s.llm.api_key_hint||'尚未设置')}" onfocus="this.placeholder=''"></div>
       <div class="field"><label>文本模型</label>
         <input id="f-llm-model" value="${esc(s.llm.model)}">
         <div class="hint">任意 OpenAI 兼容模型；deepseek 系自动关闭思考模式以提速</div>
       </div>
       <div class="field"><label>切片目标时长（秒）</label>
         <input id="f-chunk" type="number" value="${+s.chunk_seconds}">
         <div class="hint">长音频按此长度在静音处切片并行转写</div>
       </div>
       <div class="field"><label>Whisper 模型规格</label>
         <select id="f-wsize">${['tiny','base','small','medium','large-v3'].map(x=>
           `<option value="${x}" ${s.whisper_model_size===x?'selected':''}>${x}</option>`).join('')}</select>
       </div>
     </div>
     <div class="field"><label>参会人（可选）</label>
       <input id="f-attendees" value="${esc(s.attendees||'')}" placeholder="例：张三、李四">
       <div class="hint">帮助 AI 在整理稿中标注发言归属</div></div>
     <div class="field"><label>热词表（可选 · 项目专名）</label>
       <textarea id="f-hotwords" rows="3" placeholder="每行一个或逗号分隔。例：产品名、专有名词、术语...">${esc(s.hotwords||'')}</textarea>
       <div class="hint">修正 ASR 对人名/项目名/术语的识别错误</div></div>
     <div class="action-bar"><button class="btn primary" id="saveSettings">保存设置</button></div>
   </div></div>`;
  document.getElementById('saveSettings').onclick=async()=>{
    const g=id=>document.getElementById(id).value.trim();
    const body={transcriber:g('f-transcriber'),
      asr:{base_url:g('f-asr-url'), model:g('f-asr-model')},
      llm:{base_url:g('f-llm-url'), model:g('f-llm-model')},
      chunk_seconds:+g('f-chunk')||600, whisper_model_size:g('f-wsize'),
      attendees:g('f-attendees'), hotwords:g('f-hotwords')};
    if(g('f-asr-key')) body.asr.api_key=g('f-asr-key');
    if(g('f-llm-key')) body.llm.api_key=g('f-llm-key');
    try{ await api('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)}); toast('✅ 设置已保存'); closeSettings(); }
    catch(e){ alert('保存失败：'+e.message) }
  };
  document.getElementById('modalClose').onclick=closeSettings;
  document.addEventListener('keydown', escSettings);
}

/* ---------- 轮询 & 路由 ---------- */
function startPoll(fn,ms){ stopPoll(); pollTimer=setInterval(fn,ms) }
function stopPoll(){ if(pollTimer){clearInterval(pollTimer);pollTimer=null} }


/* ---------- 看板 ---------- */
let statsRange='all';
async function renderStats(){
  setNav('stats'); stopPoll();
  const R=[['all','全部'],['year','今年'],['month','本月'],['week','本周'],['day','今日']];
  $app.innerHTML=`
    <div class="stats-head">
      <a href="#/" class="back-link">← 返回</a>
      <div class="range-tabs">${R.map(([v,l])=>
        `<button class="range-tab ${statsRange===v?'active':''}" data-r="${v}">${l}</button>`).join('')}</div>
    </div>
    <div id="statsBody"><div class="empty">统计中…</div></div>`;
  $app.querySelectorAll('.range-tab').forEach(b=>b.onclick=()=>{ statsRange=b.dataset.r; renderStats() });
  const s=await api(`/api/stats?range=${statsRange}`);
  const t=s.totals;
  const hours=(t.duration_sec/3600);
  const fun = t.count===0 ? '这段时间还没有会议，传一段录音试试'
    : hours>=1 ? `这些会议加起来聊了 ${hours.toFixed(1)} 小时 ≈ ${(hours/2).toFixed(1)} 部电影的时长`
    : `这些会议共 ${Math.round(t.duration_sec/60)} 分钟，比一部短片还紧凑`;
  const cards=[
    ['🗣️','会议场数', t.count, '场'],
    ['⏱️','总时长', t.duration_sec>=3600?hours.toFixed(1):Math.round(t.duration_sec/60), t.duration_sec>=3600?'小时':'分钟'],
    ['✅','已完成', `${t.done} / ${t.done_rate}%`, ''],
    ['📝','转写字数', t.chars>=10000?(t.chars/10000).toFixed(1)+'万':t.chars, '字'],
    ['🎯','待办事项', t.todos, '项'],
    [s.peak_hour!=null?'🕐':'🕐', '最常开会', s.peak_hour!=null?`${s.peak_hour} 点`:'—', s.peak_hour!=null?'时段':''],
  ];
  const maxT=Math.max(...s.trend.map(x=>x.count),1);
  const trendHtml = s.trend.length? `<div class="trend-chart">${s.trend.map(x=>`
      <div class="trend-col" title="${esc(x.label)}：${x.count} 场">
        <div class="trend-bar" style="height:${Math.max(4, x.count/maxT*100)}%"></div>
        <div class="trend-label">${esc(x.label)}</div>
        <div class="trend-num">${x.count||''}</div>
      </div>`).join('')}</div>`
    : `<div class="empty">该范围内暂无会议</div>`;
  const hourDist=s.hour_dist||[];
  const maxH=Math.max(...hourDist.map(x=>x.count),1);
  const hourHtml = hourDist.length? `<div class="trend-chart">${hourDist.map(x=>`
      <div class="trend-col" title="${x.label}：${x.count} 场">
        <div class="trend-bar" style="height:${Math.max(4, x.count/maxH*100)}%"></div>
        <div class="trend-label">${x.label}</div>
        <div class="trend-num">${x.count||''}</div>
      </div>`).join('')}</div>`
    : `<div class="empty">该范围内暂无会议</div>`;
  const maxP=Math.max(...s.projects.map(p=>p.count),1);
  const projHtml = s.projects.length? s.projects.map(p=>`
      <div class="proj-bar-row">
        <span class="pb-name">${esc(p.name)}</span>
        <div class="pb-track"><div class="pb-fill" style="width:${p.count/maxP*100}%"></div></div>
        <span class="pb-num">${p.count} 场 · ${Math.round((p.duration||0)/60)}min</span>
      </div>`).join('') : `<div class="empty">暂无项目</div>`;
  // 热力图
  const lv=c=>c===0?0:c===1?1:c<=2?2:c<=4?3:4;
  const weeks=[];
  for(let i=0;i<s.calendar.length;i+=7) weeks.push(s.calendar.slice(i,i+7));
  const heatHtml=`<div class="heat-wrap"><div class="heat-grid">${
    weeks.map(w=>`<div class="heat-week">${w.map(d=>
      `<div class="heat-cell lv${lv(d.count)}" title="${d.date}：${d.count} 场"></div>`).join('')}</div>`).join('')
  }</div><div class="heat-legend">少 <span class="heat-cell lv0"></span><span class="heat-cell lv1"></span><span class="heat-cell lv2"></span><span class="heat-cell lv3"></span><span class="heat-cell lv4"></span> 多（近一年）</div></div>`;

  document.getElementById('statsBody').innerHTML=`
    <div class="stat-cards">${cards.map(([ic,name,val,unit])=>`
      <div class="stat-card"><div class="sc-icon">${ic}</div>
        <div class="sc-val">${val}<span class="sc-unit">${unit}</span></div>
        <div class="sc-name">${name}</div></div>`).join('')}</div>
    <div class="stat-fun">💡 ${esc(fun)}</div>
    <div class="stat-card-lg"><h3>📈 会议数量趋势</h3>${trendHtml}</div>
    <div class="stat-grid2">
      <div class="stat-card-lg"><h3>🗂️ 项目分布</h3>${projHtml}</div>
      <div class="stat-card-lg"><h3>🕐 时段分布</h3>${hourHtml}</div>
    </div>
    <div class="stat-card-lg"><h3>📅 会议日历</h3>${heatHtml}</div>`;
}

window.addEventListener('hashchange',route);
document.getElementById('navSettings')?.addEventListener('click', openSettings);
async function route(){
  const h=location.hash;
  if(h.startsWith('#/m/')) await renderDetail(h.slice(4));
  else if(h==='#/stats') await renderStats();
  else await renderList();
}
route();
