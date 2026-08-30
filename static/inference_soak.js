let latestInferenceSoak = null;

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
    '<button class="secondary" onclick="applyInferenceSoakPreset()">Production preset을 Tuning에 적용</button>',
    '</div>',
    '<div class="subtle top-gap">Production gate는 최소 30분 실측을 요구합니다. 더 짧은 실행도 smoke report로 저장되지만 production eligible로 판정하지 않습니다. Reload stress는 기본 OFF입니다.</div>',
    '<div id="inferenceSoakResult" class="subtle top-gap">Soak 미실행</div>',
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
  toast(`Production preset 적용 · shared-device=${settings.max_device_executions ?? 1} 고정 · API 시작/재시작으로 적용하세요.`);
}

window.startInferenceSoak = startInferenceSoak;
window.loadInferenceSoak = loadInferenceSoak;
window.applyInferenceSoakPreset = applyInferenceSoakPreset;
window.addEventListener('DOMContentLoaded', () => {
  ensureInferenceSoakControls();
  loadInferenceSoak();
});
