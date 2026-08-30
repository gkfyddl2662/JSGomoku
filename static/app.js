let selectedJob = null;
let pollTimer = null;

async function api(path, options={}) {
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error(data?.detail || text || `HTTP ${res.status}`);
  return data;
}

function toast(msg, error=false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.background = error ? '#ffd8dd' : '#e7f6ff';
  el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(()=>el.classList.remove('show'), 2600);
}

function bytes(n) {
  if (!Number.isFinite(n)) return '-';
  const u=['B','KB','MB','GB','TB']; let i=0; let x=n;
  while(x>=1024 && i<u.length-1){x/=1024;i++;}
  return `${x.toFixed(i>1?2:1)} ${u[i]}`;
}

async function loadSystem() {
  try {
    const s = await api('/api/system');
    const g = s.gpus?.[0];
    document.getElementById('gpuName').textContent = g?.name || 'NVIDIA GPU not found';
    document.getElementById('gpuVram').textContent = g ? `${(g.memory_used_mb/1024).toFixed(1)} / ${(g.memory_total_mb/1024).toFixed(1)} GB` : '-';
    document.getElementById('gpuUtil').textContent = g ? `${g.utilization_pct}%` : '-';
    document.getElementById('gpuTemp').textContent = g ? `${g.temperature_c}°C` : '-';
    document.getElementById('gpuPower').textContent = g ? `${g.power_w} / ${g.power_limit_w} W` : '-';
    const t=s.torch||{};
    document.getElementById('torchInfo').textContent = `PyTorch ${t.version||'?'} · CUDA ${t.cuda||'?'} · ${t.available?'CUDA ready':'CUDA unavailable'}${t.capability?` · CC ${t.capability.join('.')}`:''}`;
  } catch(e){ toast(e.message,true); }
}

async function loadSetup() {
  try {
    const s=await api('/api/setup/status');
    const badge=document.getElementById('setupBadge');
    badge.textContent=s.ready?'READY':'SETUP REQUIRED'; badge.classList.toggle('ok',s.ready);
    document.getElementById('setupChecks').innerHTML=Object.entries(s.checks).map(([k,v])=>`<div class="check ${v?'ok':''}">${v?'●':'○'} ${k}</div>`).join('');
  } catch(e){ toast(e.message,true); }
}

async function loadEvaluation() {
  try {
    const e=await api('/api/evaluation/backends');
    const p3=e.primary?.['3p'];
    const p4=e.primary?.['4p'];
    const runtime=e.runtime||{};
    const rows=[
      ['3P Primary', p3?.name||'-'],
      ['4P Primary', p4?.name||'-'],
      ['MJX Ref', runtime.mjx_ref||'-'],
      ['WSL2', runtime.wsl_available?'READY':'NOT FOUND'],
    ];
    document.getElementById('evaluationBackends').innerHTML=rows.map(([a,b])=>`<div><label>${a}</label><strong>${b}</strong></div>`).join('');
    document.getElementById('evaluationNote').textContent = `4P ${p4?.name||'-'} · ${p4?.batched_agent?'batched inference':'single inference'} · 3P ${p3?.name||'-'} · MJX runtime ${runtime.mjx_runtime||'wsl2'} / Python ${runtime.mjx_python||'3.11'}`;
  } catch(e){ toast(`평가 backend: ${e.message}`,true); }
}

function mjxArgs(){
  return {
    distro: document.getElementById('mjxDistro')?.value || '',
    linux_root: document.getElementById('mjxLinuxRoot')?.value || '~/mortal-rogs-mjx',
  };
}

async function setupMjx(){ return startJob('mjx_setup', mjxArgs()); }
async function probeMjx(){ return startJob('mjx_probe', mjxArgs()); }

async function loadData() {
  try {
    const d=await api('/api/data');
    const rows=[['JSONL',d.data?.jsonl??0],['Data',bytes(d.data?.bytes||0)],['Models',bytes(d.models?.bytes||0)],['Runs',bytes(d.runs?.bytes||0)]];
    document.getElementById('dataStats').innerHTML=rows.map(([a,b])=>`<div><label>${a}</label><strong>${b}</strong></div>`).join('');
  } catch(e){ toast(e.message,true); }
}

async function loadConfig() {
  try {
    const d=await api('/api/config');
    document.getElementById('configPath').textContent=d.path;
    document.getElementById('configEditor').value=JSON.stringify(d.config,null,2);
  } catch(e){ document.getElementById('configEditor').value=''; toast(e.message,true); }
}

async function saveConfig() {
  try {
    const config=JSON.parse(document.getElementById('configEditor').value);
    await api('/api/config',{method:'PUT',body:JSON.stringify({config})}); toast('설정을 저장했습니다.');
  } catch(e){ toast(`저장 실패: ${e.message}`,true); }
}

async function applyPreset() {
  try { await api('/api/config/preset/rtx5080/apply',{method:'POST'}); await loadConfig(); toast('RTX 5080 프리셋 적용 완료'); }
  catch(e){ toast(e.message,true); }
}

async function setOnline(value) {
  const d=await api('/api/config'); d.config.control.online=value;
  await api('/api/config',{method:'PUT',body:JSON.stringify({config:d.config})});
  await loadConfig(); toast(value?'Online self-play 모드':'Offline 학습 모드');
}

async function startJob(kind,args={}) {
  try { const j=await api('/api/jobs',{method:'POST',body:JSON.stringify({kind,args})}); selectedJob=j.id; await loadJobs(); toast(`${kind} 시작`); }
  catch(e){ toast(e.message,true); }
}

async function startSelfPlay() {
  try {
    await setOnline(true);
    await startJob('selfplay_server');
    await new Promise(r=>setTimeout(r,700));
    await startJob('selfplay_client');
    await startJob('train');
    toast('Self-play server + client + trainer 시작');
  } catch(e){ toast(e.message,true); }
}

function startTenhou(){ return startJob('tenhou_dl',{source:document.getElementById('tenhouSource').value,output:document.getElementById('tenhouOutput').value}); }
function startConvert(){ return startJob('convert',{source:document.getElementById('convertSource').value,output:document.getElementById('convertOutput').value}); }

async function loadCheckpoints() {
  try {
    const rows=await api('/api/checkpoints');
    document.getElementById('checkpoints').innerHTML=rows.length?rows.slice(0,30).map(x=>`<div class="list-item"><div><strong>${x.relative}</strong><div class="meta">${bytes(x.bytes)} · ${new Date(x.mtime*1000).toLocaleString()}</div></div><button class="mini" onclick="promote('${esc(x.relative)}')">Best로 승격</button></div>`).join(''):'<div class="subtle">checkpoint가 없습니다.</div>';
  } catch(e){ toast(e.message,true); }
}

async function promote(source) {
  try { await api('/api/checkpoints/promote',{method:'POST',body:JSON.stringify({source,destination:'best_sanma.pth'})}); toast('best_sanma.pth로 복사했습니다.'); await loadCheckpoints(); }
  catch(e){ toast(e.message,true); }
}

function esc(s){return s.replaceAll('\\','\\\\').replaceAll("'","\\'");}

async function loadJobs() {
  try {
    const rows=await api('/api/jobs');
    const root=document.getElementById('jobs');
    root.innerHTML=rows.length?rows.map(j=>`<div class="list-item job ${selectedJob===j.id?'selected':''}" onclick="selectJob('${j.id}')"><div><strong><span class="dot ${j.running?'running':''}"></span>${j.kind}</strong><div class="meta">${j.id} · ${j.running?'RUNNING':`EXIT ${j.returncode}`}</div></div><span class="meta">${new Date(j.started_at*1000).toLocaleTimeString()}</span></div>`).join(''):'<div class="subtle">실행 기록이 없습니다.</div>';
    if(selectedJob) await loadSelectedJob();
  } catch(e){ toast(e.message,true); }
}

async function selectJob(id){ selectedJob=id; await loadJobs(); }

async function loadSelectedJob() {
  try {
    const j=await api(`/api/jobs/${selectedJob}`);
    document.getElementById('logTitle').textContent=`${j.kind} · ${j.id}`;
    document.getElementById('stopButton').disabled=!j.running;
    const log=document.getElementById('logs');
    const atBottom=log.scrollTop+log.clientHeight>=log.scrollHeight-80;
    log.textContent=(j.logs||[]).join('\n') || '(no output yet)';
    if(atBottom) log.scrollTop=log.scrollHeight;
  } catch(e){ selectedJob=null; }
}

async function stopSelected(){ if(!selectedJob)return; try{await api(`/api/jobs/${selectedJob}/stop`,{method:'POST'});toast('프로세스를 중지했습니다.');await loadJobs();}catch(e){toast(e.message,true);} }

async function refreshAll(){ await Promise.all([loadSystem(),loadSetup(),loadEvaluation(),loadData(),loadCheckpoints(),loadJobs()]); }

window.addEventListener('load', async()=>{
  await refreshAll(); await loadConfig();
  pollTimer=setInterval(async()=>{ await Promise.all([loadSystem(),loadJobs()]); },2500);
});
