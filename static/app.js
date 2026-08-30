let selectedJob = null;
let pollTimer = null;

function currentMode() {
  return document.getElementById('gameMode')?.value || '3p';
}

function modeQuery() {
  return `mode=${encodeURIComponent(currentMode())}`;
}

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

async function changeGameMode() {
  const mode=currentMode();
  localStorage.setItem('mortalGameMode', mode);
  const label=mode==='3p'?'3P':'4P';
  document.getElementById('runtimeTitle').textContent=`${label} Environment`;
  document.getElementById('pipelineTitle').textContent=`${label} 학습 제어`;
  document.getElementById('dataTitle').textContent=`${label} 데이터 파이프라인`;
  document.getElementById('checkpointTitle').textContent=`${label} 모델 관리`;
  document.getElementById('configTitle').textContent=`${label} Mortal config`;
  document.getElementById('tensorboardLink').href=mode==='3p'?'http://127.0.0.1:6006':'http://127.0.0.1:6007';
  document.getElementById('sanmaDataTools').hidden=mode!=='3p';
  document.getElementById('yonmaDataNote').hidden=mode!=='4p';
  document.getElementById('promotionMode').value=mode;
  syncPromotionDestination();
  document.getElementById('promotionCandidate').value='';
  await Promise.all([loadSetup(),loadData(),loadCheckpoints(),loadConfig(),loadInference()]);
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
    document.getElementById('torchInfo').textContent = `WebUI PyTorch ${t.version||'?'} · CUDA ${t.cuda||'?'} · ${t.available?'CUDA ready':'CUDA unavailable'}${t.capability?` · CC ${t.capability.join('.')}`:''}`;
  } catch(e){ toast(e.message,true); }
}

async function loadSetup() {
  try {
    const s=await api(`/api/setup/status?${modeQuery()}`);
    const badge=document.getElementById('setupBadge');
    badge.textContent=s.ready?`${s.mode.toUpperCase()} READY`:`${s.mode.toUpperCase()} SETUP REQUIRED`;
    badge.classList.toggle('ok',s.ready);
    document.getElementById('runtimePath').textContent=`${s.mortal_root} · Python ${s.python}`;
    document.getElementById('setupChecks').innerHTML=Object.entries(s.checks).map(([k,v])=>`<div class="check ${v?'ok':''}">${v?'●':'○'} ${k}</div>`).join('');
  } catch(e){ toast(e.message,true); }
}

async function loadEvaluation() {
  try {
    const e=await api('/api/evaluation/backends');
    const p3=e.primary?.['3p'];
    const p4=e.primary?.['4p'];
    const sanma=e.backends?.mjx_sanma;
    const runtime=e.runtime||{};
    const rows=[
      ['3P Production', p3?.name||'-'],
      ['3P Target', sanma?.name ? `${sanma.name}${sanma.experimental?' · EXP':''}` : '-'],
      ['4P Primary', p4?.name||'-'],
      ['MJX Ref', runtime.mjx_ref||'-'],
      ['WSL2', runtime.wsl_available?'READY':'NOT FOUND'],
    ];
    document.getElementById('evaluationBackends').innerHTML=rows.map(([a,b])=>`<div><label>${a}</label><strong>${b}</strong></div>`).join('');
    document.getElementById('evaluationNote').textContent = `4P ${p4?.name||'-'} · ${p4?.batched_agent?'batched inference':'single inference'} · 3P production ${p3?.name||'-'} → target ${sanma?.name||'mjx_sanma'} · parity gate required`;
  } catch(e){ toast(`평가 backend: ${e.message}`,true); }
}

async function loadInference() {
  try {
    const s=await api('/api/inference/status');
    const el=document.getElementById('inferenceStatus');
    if(!el) return;
    el.textContent=s.unified
      ? `${s.default_url} · 3P ${s.endpoints?.['3p']} · 4P ${s.endpoints?.['4p']} · Best 모델 자동 재로딩`
      : 'Unified runtime 설치가 필요합니다.';
  } catch(e){ toast(`Inference API: ${e.message}`,true); }
}

async function startInferenceApi() {
  const body={
    host: document.getElementById('inferenceHost').value || '127.0.0.1',
    port: Number(document.getElementById('inferencePort').value || 8190),
    api_key: document.getElementById('inferenceApiKey').value || '',
    device: document.getElementById('inferenceDevice').value || 'auto',
  };
  try {
    const j=await api('/api/inference/start',{method:'POST',body:JSON.stringify(body)});
    selectedJob=j.id;
    await loadJobs();
    toast(`Akagi API 시작 · http://${body.host}:${body.port}`);
  } catch(e){ toast(e.message,true); }
}

function mjxArgs(){
  return {
    distro: document.getElementById('mjxDistro')?.value || '',
    linux_root: document.getElementById('mjxLinuxRoot')?.value || '~/mortal-rogs-mjx',
  };
}

function mjxSanmaArgs(){
  return {
    root: document.getElementById('mjxSanmaRoot')?.value || 'C:\\Mortal_ROGS\\mjx-sanma',
    through: Number(document.getElementById('mjxSanmaThrough')?.value || 3),
  };
}

async function bootstrapRuntime(){ return startJob('bootstrap_unified_runtime',{install_rust_if_missing:true}); }
async function setupMjx(){ return startJob('mjx_setup', mjxArgs()); }
async function probeMjx(){ return startJob('mjx_probe', mjxArgs()); }
async function prepareMjxSanma(){ return startJob('mjx_sanma_prepare', mjxSanmaArgs()); }
async function patchMjxSanma(){ return startJob('mjx_sanma_patch', mjxSanmaArgs()); }
async function auditMjxSanma(){ return startJob('mjx_sanma_audit', mjxSanmaArgs()); }

async function loadData() {
  try {
    const d=await api(`/api/data?${modeQuery()}`);
    const rows=[
      ['JSONL',d.data?.jsonl??0],
      ['JSON.GZ',d.data?.json_gz??d.data?.gz??0],
      ['Data',bytes(d.data?.bytes||0)],
      ['Models',bytes(d.models?.bytes||0)],
      ['Runs',bytes(d.runs?.bytes||0)],
    ];
    document.getElementById('dataStats').innerHTML=rows.map(([a,b])=>`<div><label>${a}</label><strong>${b}</strong></div>`).join('');
  } catch(e){ toast(e.message,true); }
}

async function loadConfig() {
  try {
    const d=await api(`/api/config?${modeQuery()}`);
    document.getElementById('configPath').textContent=d.path;
    document.getElementById('configEditor').value=JSON.stringify(d.config,null,2);
  } catch(e){ document.getElementById('configEditor').value=''; toast(e.message,true); }
}

async function saveConfig() {
  try {
    const config=JSON.parse(document.getElementById('configEditor').value);
    await api(`/api/config?${modeQuery()}`,{method:'PUT',body:JSON.stringify({config})});
    toast(`${currentMode().toUpperCase()} 설정을 저장했습니다.`);
  } catch(e){ toast(`저장 실패: ${e.message}`,true); }
}

async function applyPreset() {
  try {
    await api(`/api/config/preset/rtx5080/apply?${modeQuery()}`,{method:'POST'});
    await loadConfig();
    toast(`${currentMode().toUpperCase()} RTX 5080 프리셋 적용 완료`);
  } catch(e){ toast(e.message,true); }
}

async function setOnline(value) {
  const d=await api(`/api/config?${modeQuery()}`);
  if(!d.config.control) d.config.control={};
  d.config.control.online=value;
  await api(`/api/config?${modeQuery()}`,{method:'PUT',body:JSON.stringify({config:d.config})});
  await loadConfig(); toast(value?'Online self-play 모드':'Offline 학습 모드');
}

async function startJob(kind,args={}) {
  const routedArgs={mode:currentMode(), ...args};
  try {
    const j=await api('/api/jobs',{method:'POST',body:JSON.stringify({kind,args:routedArgs})});
    selectedJob=j.id;
    await loadJobs();
    toast(`${kind} · ${routedArgs.mode.toUpperCase()} 시작`);
    return j;
  } catch(e){ toast(e.message,true); throw e; }
}

async function startSelfPlay() {
  try {
    await setOnline(true);
    await startJob('selfplay_server');
    await new Promise(r=>setTimeout(r,700));
    await startJob('selfplay_client');
    await startJob('train');
    toast(`${currentMode().toUpperCase()} Self-play server + client + trainer 시작`);
  } catch(e){ toast(e.message,true); }
}

function startTenhou(){ return startJob('tenhou_dl',{source:document.getElementById('tenhouSource').value,output:document.getElementById('tenhouOutput').value}); }
function startConvert(){ return startJob('convert',{source:document.getElementById('convertSource').value,output:document.getElementById('convertOutput').value}); }

async function loadCheckpoints() {
  try {
    const rows=await api(`/api/checkpoints?${modeQuery()}`);
    document.getElementById('checkpoints').innerHTML=rows.length?rows.slice(0,30).map(x=>`<div class="list-item"><div><strong>${x.relative}</strong><div class="meta">${x.mode.toUpperCase()} · ${bytes(x.bytes)} · ${new Date(x.mtime*1000).toLocaleString()}</div></div><button class="mini" onclick="selectPromotionCandidate('${esc(x.relative)}')">승격 후보</button></div>`).join(''):'<div class="subtle">checkpoint가 없습니다.</div>';
  } catch(e){ toast(e.message,true); }
}

function selectPromotionCandidate(source) {
  document.getElementById('promotionCandidate').value=source;
  document.getElementById('promotionMode').value=currentMode();
  syncPromotionDestination();
  toast(`승격 후보 선택: ${source}`);
}

function syncPromotionDestination() {
  document.getElementById('promotionDestination').value = 'best_mortal.pth';
}

async function runGatedPromotion() {
  const body={
    source: document.getElementById('promotionCandidate').value,
    destination: document.getElementById('promotionDestination').value || 'best_mortal.pth',
    paired_results: document.getElementById('promotionResults').value,
    profile: document.getElementById('promotionProfile').value,
    mode: document.getElementById('promotionMode').value,
  };
  if(!body.source || !body.paired_results || !body.profile){
    toast('Candidate, paired 결과, profile을 모두 입력하세요.', true);
    return;
  }
  try {
    const j=await api('/api/promotion/start',{method:'POST',body:JSON.stringify(body)});
    selectedJob=j.id;
    await loadJobs();
    toast('Promotion Gate 실행: 통계 + Mortal API ABI를 모두 통과해야 Best가 교체됩니다.');
  } catch(e){ toast(e.message,true); }
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

async function refreshAll(){ await Promise.all([loadSystem(),loadSetup(),loadEvaluation(),loadInference(),loadData(),loadCheckpoints(),loadJobs()]); }

window.addEventListener('load', async()=>{
  const saved=localStorage.getItem('mortalGameMode');
  if(saved==='3p' || saved==='4p') document.getElementById('gameMode').value=saved;
  await changeGameMode();
  await Promise.all([loadSystem(),loadEvaluation(),loadInference(),loadJobs()]);
  pollTimer=setInterval(async()=>{ await Promise.all([loadSystem(),loadJobs()]); },2500);
});
