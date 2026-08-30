let latestInferenceSoak = null;
let latestInferenceProductionProfile = null;

function soakNumber(id, fallback) {
  const value = Number(document.getElementById(id)?.value);
  return Number.isFinite(value) ? value : fallback;
}

function ensureInferenceSoakControls() {
  let root = document.getElementById('inferenceSoak');
  if (root) return root;
  const benchmark = document.getElementById('inferenceBenchmark') || (typeof ensureInferenceBenchmarkControls === 'function' ? ensureInferenceBenchmarkControls() : null);
  const telemetry = document.getElementById('inferenceTelemetry');
  const anchor = benchmark || telemetry;
  if (!anchor) return null;
  root = document.createElement('div');
  root.id = 'inferenceSoak';
  root.className = 'top-gap';
  root.innerHTML = [
    '<div class="form-grid">',
    '<label>Soak modes<select id="inferenceSoakModes"><option value="both" selected>3P + 4P</option><option value="3p">3P only</option><option value="4p">4P only</option></select></label>',
    '<label>Duration (minutes)<input id="inferenceSoakMinutes" type="number" value="30" min="0.05" max="1440" step="5" /></label>',
    '<label>Concurrency<input id="inferenceSoakConcurrency" type="number" value="8" min="1" max="256" step="1" /></label>',
    '<label>Rows / request<input id="inferenceSoakRows" type="number" value="1" min="1" max="64" step="1" /></label>',
    '<label>Sample interval (s)<input id="inferenceSoakSampleInterval" type="number" value="1" min="0.2" max="60" step="0.2" /></label>',
    '<label>p95 budget (ms)<input id="inferenceSoakP95" type="number" value="100" min="1" max="1000" step="5" /></label>',
    '<label>p99 budget (ms)<input id="inferenceSoakP99" type="number" value="250" min="1" max="3500" step="10" /></label>',
    '<label>VRAM ceiling (%)<input id="inferenceSoakVram" type="number" value="92" min="1" max="100" step="0.5" /></label>',
    '<label>Temperature ceiling (°C)<input id="inferenceSoakTemp" type="number" value="88" min="1" max="120" step="1" /></label>',
    '<label>Reload stress interval (minutes, 0=off)<input id="inferenceSoakReload" type="number" value="0" min="0" max="1440" step="1" /></label>',
    '<label><input id="inferenceSoakRequireGpu" type="checkbox" checked /> NVIDIA GPU telemetry 필수</label>',
    '</div>',
    '<div class="button-row top-gap">',
    '<button class="secondary" onclick="startInferenceSoak()">RTX 5080 Production Soak 시작</button>',
    '<button class="secondary" onclick="loadInferenceSoak()">최신 Soak 결과</button>',
    '<button class="secondary" onclick="applyInferenceSoakPreset()">Preset을 Tuning에 복사</button>',
    '<button onclick="applyInferenceProductionProfile()">Production preset 원자 적용</button>',
    '<button class="secondary" onclick="loadInferenceProductionProfile()">Production profile 상태</button>',
    '</div>',
    '<div class="subtle top-gap">Production gate는 최소 30분 실측을 요구합니다. 원자 적용은 profile 저장 → graceful drain → 재시작 → health/모델/serving 설정 검증 순서로 수행하며, 실패하면 이전 profile과 서버 설정으로 자동 rollback합니다.</div>',
    '<div id="inferenceSoakResult" class="subtle top-gap">Soak 미실행</div>',
    '<div id="inferenceProductionProfileResult" class="subtle top-gap">Production profile 확인 중…</div>',
  ].join('');
  anchor.insertAdjacentElement('afterend', root);
  return root;
}

function soakModeText(mode, result) {
  if (!result) return `${mode.toUpperCase()} -`;
  const latency = result.latency_ms || {};
  return `${mode.toUpperCase()} p95 ${inferenceMetricNumber(latency.p95,1)}ms · p99 ${inferenceMetricNumber(latency.p99,1)}ms · ${inferenceMetricNumber(result.rows_per_s,1)} rows/s · fail ${result.failed_requests ?? '-'}`;
}

function renderInferenceSoak(report, path='') {
  ensureInferenceSoakControls();
  latestInferenceSoak = report || null;
  const el = document.getElementById('inferenceSoakResult');
  if (!el) return;
  if (!report) { el.textContent = 'Soak 결과가 없습니다.'; return; }
  const gate = report.production_gate || {};
  const observed = gate.observed || {};
  const gpu = report.gpu || {};
  const device = report.device_scheduler || {};
  const preset = report.production_preset || {};
  const elapsedMin = Number(report.elapsed_s || 0) / 60;
  const gateText = gate.passed ? 'PRODUCTION PASS' : (gate.validation_level === 'smoke' ? 'SMOKE · NOT ELIGIBLE' : 'PRODUCTION BLOCKED');
  const modeText = [soakModeText('3p', report.modes?.['3p']), soakModeText('4p', report.modes?.['4p'])].filter(x => !x.endsWith(' -')).join(' · ');
  const gpuText = gpu.available
    ? `GPU ${gpu.name || ''} · VRAM ${inferenceMetricNumber((gpu.peak_memory_used_mb||0)/1024,2)}GB/${inferenceMetricNumber(gpu.peak_memory_used_pct,1)}% · util ${inferenceMetricNumber(gpu.peak_utilization_pct,0)}% · ${inferenceMetricNumber(gpu.peak_temperature_c,0)}°C · ${inferenceMetricNumber(gpu.peak_power_w,0)}W`
    : `GPU telemetry ${gpu.last_error || 'unavailable'}`;
  const deviceText = `device peak ${device.peak_active_executions ?? '-'} · waiting peak ${device.peak_waiting_executions ?? '-'} · contention ${device.contended_acquisitions_total ?? '-'} · wait p95 ${inferenceMetricNumber(device.wait_ms?.p95,1)}ms`;
  el.textContent = `${gateText} · ${elapsedMin.toFixed(1)}m · ${modeText} · ${gpuText} · ${deviceText} · preset ${preset.eligible ? 'READY' : 'BLOCKED'}${path ? ` · ${path}` : ''}${observed.failed_requests ? ` · failed ${observed.failed_requests}` : ''}`;
}

function renderInferenceProductionProfile(result) {
  ensureInferenceSoakControls();
  latestInferenceProductionProfile = result?.profile || null;
  const el = document.getElementById('inferenceProductionProfileResult');
  if (!el) return;
  if (!result?.available || !result.profile) {
    el.textContent = `Production profile 없음${result?.path ? ` · ${result.path}` : ''}`;
    return;
  }
  const profile = result.profile;
  const serving = profile.serving || {};
  const target = profile.target || {};
  const source = profile.source || {};
  el.textContent = `Production ${String(profile.status || 'unknown').toUpperCase()} · ${target.device || '-'} · ${target.host || '-'}:${target.port || '-'} · merge ${serving.micro_batch_ms ?? '-'}ms · pending ${serving.max_pending_requests ?? '-'} · deadline ${serving.request_deadline_ms ?? '-'}ms · reload quiet/wait ${serving.reload_quiet_ms ?? '-'}/${serving.reload_wait_ms ?? '-'}ms · source ${source.report || '-'}${result.path ? ` · ${result.path}` : ''}`;
}

function inferenceSoakBody() {
  return {
    modes: document.getElementById('inferenceSoakModes')?.value || 'both',
    duration_minutes: soakNumber('inferenceSoakMinutes', 30),
    concurrency: soakNumber('inferenceSoakConcurrency', 8),
    batch_rows: soakNumber('inferenceSoakRows', 1),
    sample_interval_s: soakNumber('inferenceSoakSampleInterval', 1),
    latency_budget_ms: soakNumber('inferenceSoakP95', 100),
    p99_budget_ms: soakNumber('inferenceSoakP99', 250),
    vram_ceiling_pct: soakNumber('inferenceSoakVram', 92),
    temperature_ceiling_c: soakNumber('inferenceSoakTemp', 88),
    reload_every_minutes: soakNumber('inferenceSoakReload', 0),
    require_gpu_telemetry: Boolean(document.getElementById('inferenceSoakRequireGpu')?.checked),
  };
}

async function startInferenceSoak() {
  ensureInferenceSoakControls();
  const body = inferenceSoakBody();
  try {
    const job = await api('/api/inference/soak/start', {method:'POST', body:JSON.stringify(body)});
    selectedJob = job.id;
    await loadJobs();
    toast(`RTX 5080 soak 시작 · ${body.duration_minutes}분 · ${body.modes.toUpperCase()} · concurrency ${body.concurrency}`);
    return job;
  } catch (e) {
    toast(`Soak 시작 실패: ${e.message}`, true);
    throw e;
  }
}

async function loadInferenceSoak() {
  ensureInferenceSoakControls();
  try {
    const result = await api('/api/inference/soak/latest');
    if (!result.available) { renderInferenceSoak(null); return result; }
    renderInferenceSoak(result.report, result.path || '');
    return result;
  } catch (e) {
    toast(`Soak 결과: ${e.message}`, true);
    throw e;
  }
}

async function loadInferenceProductionProfile() {
  ensureInferenceSoakControls();
  try {
    const result = await api('/api/inference/production/status');
    renderInferenceProductionProfile(result);
    return result;
  } catch (e) {
    const el = document.getElementById('inferenceProductionProfileResult');
    if (el) el.textContent = `Production profile 오류 · ${e.message}`;
    throw e;
  }
}

function applyInferenceSoakPreset() {
  const preset = latestInferenceSoak?.production_preset;
  if (!preset?.eligible || !preset.settings) {
    toast('Production gate를 통과한 soak preset이 필요합니다.', true);
    return;
  }
  if (typeof ensureInferenceTuningControls === 'function') ensureInferenceTuningControls();
  const settings = preset.settings;
  const values = {
    inferenceMicroBatchMs: settings.micro_batch_ms,
    inferenceMaxRows: settings.micro_batch_max_rows,
    inferenceMaxPending: settings.max_pending_requests,
    inferenceDeadlineMs: settings.request_deadline_ms,
    inferenceReloadPollMs: settings.reload_poll_ms,
  };
  for (const [id, value] of Object.entries(values)) {
    const input = document.getElementById(id);
    if (input && Number.isFinite(Number(value))) input.value = String(value);
  }
  const tuning = document.getElementById('inferenceTuning');
  if (tuning) tuning.dataset.dirty = '1';
  toast(`Production preset을 입력값에 복사했습니다. shared-device=${settings.max_device_executions ?? 1}은 production 경로에서 1로 고정됩니다.`);
}

async function applyInferenceProductionProfile() {
  const preset = latestInferenceSoak?.production_preset;
  if (!preset?.eligible || latestInferenceSoak?.production_gate?.passed !== true) {
    toast('최신 30분 Production PASS soak 결과를 먼저 불러오세요.', true);
    return;
  }
  try {
    toast('Production preset 적용 시작 · graceful drain/restart/검증 후 실패 시 자동 rollback');
    const result = await api('/api/inference/production/apply', {
      method:'POST',
      body:JSON.stringify({verify_timeout_s:180}),
    });
    await Promise.all([
      typeof loadInference === 'function' ? loadInference() : Promise.resolve(),
      typeof loadInferenceTelemetry === 'function' ? loadInferenceTelemetry() : Promise.resolve(),
      loadInferenceProductionProfile(),
    ]);
    toast(`Production preset 적용 완료 · rollback ${result.rolled_back ? 'YES' : 'NO'}`);
    return result;
  } catch (e) {
    await Promise.allSettled([
      typeof loadInference === 'function' ? loadInference() : Promise.resolve(),
      typeof loadInferenceTelemetry === 'function' ? loadInferenceTelemetry() : Promise.resolve(),
      loadInferenceProductionProfile(),
    ]);
    toast(`Production preset 적용 실패 · 서버 rollback 결과를 확인하세요: ${e.message}`, true);
    throw e;
  }
}

window.startInferenceSoak = startInferenceSoak;
window.loadInferenceSoak = loadInferenceSoak;
window.applyInferenceSoakPreset = applyInferenceSoakPreset;
window.applyInferenceProductionProfile = applyInferenceProductionProfile;
window.loadInferenceProductionProfile = loadInferenceProductionProfile;
window.addEventListener('DOMContentLoaded', () => {
  ensureInferenceSoakControls();
  loadInferenceSoak();
  loadInferenceProductionProfile();
});
