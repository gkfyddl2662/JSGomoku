async function reloadInferenceModel(mode=null) {
  try {
    const payload = mode ? {mode} : {};
    const result = await api('/api/inference/reload', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    const modes = Object.keys(result.results || {}).map(x => x.toUpperCase()).join(' + ') || '3P + 4P';
    toast(`${modes} 모델 hot-reload 완료`);
    await loadInference();
    await loadInferenceTelemetry();
    return result;
  } catch (e) {
    toast(`모델 reload 실패: ${e.message}`, true);
    await loadInference();
    await loadInferenceTelemetry();
    throw e;
  }
}

function inferenceMetricNumber(value, digits=1) {
  return Number.isFinite(value) ? Number(value).toFixed(digits) : '-';
}

function inferenceNumber(id, fallback) {
  const element = document.getElementById(id);
  const value = Number(element?.value);
  return Number.isFinite(value) ? value : fallback;
}

function ensureInferenceTuningControls() {
  let controls = document.getElementById('inferenceTuning');
  if (controls) return controls;
  const status = document.getElementById('inferenceStatus');
  if (!status) return null;
  const buttonRow = status.previousElementSibling;
  controls = document.createElement('div');
  controls.id = 'inferenceTuning';
  controls.className = 'form-grid top-gap';
  controls.innerHTML = [
    '<label>Micro-batch wait (ms)<input id="inferenceMicroBatchMs" type="number" value="1" min="0" max="100" step="0.1" /></label>',
    '<label>Max batch rows<input id="inferenceMaxRows" type="number" value="64" min="1" max="4096" step="1" /></label>',
    '<label>Max pending requests<input id="inferenceMaxPending" type="number" value="128" min="1" max="4096" step="1" /></label>',
    '<label>Server deadline (ms)<input id="inferenceDeadlineMs" type="number" value="3500" min="1" max="3999" step="50" /></label>',
    '<label>Reload poll (ms)<input id="inferenceReloadPollMs" type="number" value="500" min="50" max="60000" step="50" /></label>',
  ].join('');
  if (buttonRow) buttonRow.insertAdjacentElement('beforebegin', controls);
  else status.insertAdjacentElement('beforebegin', controls);
  controls.querySelectorAll('input').forEach(input => {
    input.addEventListener('input', () => { controls.dataset.dirty = '1'; });
  });
  return controls;
}

function syncInferenceTuning(serving) {
  const controls = ensureInferenceTuningControls();
  if (!controls || controls.dataset.dirty === '1' || !serving) return;
  const schedule = serving.micro_batch || {};
  const reload = serving.reload || {};
  const values = {
    inferenceMicroBatchMs: schedule.wait_ms,
    inferenceMaxRows: schedule.max_rows,
    inferenceMaxPending: schedule.max_pending_requests,
    inferenceDeadlineMs: schedule.request_deadline_ms,
    inferenceReloadPollMs: reload.poll_ms,
  };
  for (const [id, value] of Object.entries(values)) {
    const input = document.getElementById(id);
    if (input && Number.isFinite(value)) input.value = String(value);
  }
}

async function startInferenceApi() {
  ensureInferenceTuningControls();
  const body={
    host: document.getElementById('inferenceHost').value || '127.0.0.1',
    port: Number(document.getElementById('inferencePort').value || 8190),
    api_key: document.getElementById('inferenceApiKey').value || '',
    device: document.getElementById('inferenceDevice').value || 'auto',
    micro_batch_ms: inferenceNumber('inferenceMicroBatchMs', 1),
    micro_batch_max_rows: inferenceNumber('inferenceMaxRows', 64),
    max_pending_requests: inferenceNumber('inferenceMaxPending', 128),
    request_deadline_ms: inferenceNumber('inferenceDeadlineMs', 3500),
    reload_poll_ms: inferenceNumber('inferenceReloadPollMs', 500),
  };
  if (body.request_deadline_ms <= 0 || body.request_deadline_ms >= 4000) {
    toast('Server deadline은 AkagiOT 4초 read timeout보다 짧은 1~3999ms여야 합니다.', true);
    return;
  }
  try {
    const j=await api('/api/inference/start',{method:'POST',body:JSON.stringify(body)});
    selectedJob=j.id;
    const controls=document.getElementById('inferenceTuning');
    if (controls) delete controls.dataset.dirty;
    await loadJobs();
    toast(`Akagi API 시작 · http://${body.host}:${body.port} · ${body.micro_batch_ms}ms/${body.micro_batch_max_rows} rows`);
    setTimeout(()=>Promise.all([loadInference(),loadInferenceTelemetry()]),800);
  } catch(e){ toast(e.message,true); }
}

function ensureInferenceTelemetryElement() {
  let el = document.getElementById('inferenceTelemetry');
  if (el) return el;
  const status = document.getElementById('inferenceStatus');
  if (!status) return null;
  el = document.createElement('div');
  el.id = 'inferenceTelemetry';
  el.className = 'metrics compact top-gap';
  status.insertAdjacentElement('afterend', el);
  return el;
}

function inferenceModeMetric(mode, metrics) {
  const request = metrics?.latency_ms?.request || {};
  const model = metrics?.latency_ms?.model || {};
  const queue = metrics?.latency_ms?.queue || {};
  const batch = inferenceMetricNumber(metrics?.avg_rows_per_execution, 2);
  const p95 = inferenceMetricNumber(request?.p95, 1);
  const modelP95 = inferenceMetricNumber(model?.p95, 1);
  const queueP95 = inferenceMetricNumber(queue?.p95, 1);
  const rate = inferenceMetricNumber(metrics?.row_rate_per_s, 1);
  const depth = Number.isFinite(metrics?.queue_depth) ? metrics.queue_depth : '-';
  const peak = Number.isFinite(metrics?.peak_queue_depth) ? metrics.peak_queue_depth : '-';
  const merged = Number.isFinite(metrics?.coalesced_requests_total) ? metrics.coalesced_requests_total : '-';
  const rejects = Number.isFinite(metrics?.busy_rejections_total) ? metrics.busy_rejections_total : '-';
  const timeouts = Number.isFinite(metrics?.timeouts_total) ? metrics.timeouts_total : '-';
  return `${mode.toUpperCase()} p95 ${p95}ms · GPU/model ${modelP95}ms · queue ${queueP95}ms · ${rate} rows/s · batch ${batch} · q ${depth}/${peak} · merged ${merged} · 503 ${rejects} · timeout ${timeouts}`;
}

function inferenceDeviceMetric(device) {
  const wait = device?.wait_ms || {};
  return `fair ${device?.policy || '-'} · active ${device?.active_executions ?? '-'}/${device?.max_parallel_executions ?? '-'} · waiting ${device?.waiting_executions ?? '-'} · peak ${device?.peak_active_executions ?? '-'} · contention ${device?.contended_acquisitions_total ?? '-'} · wait p95 ${inferenceMetricNumber(wait.p95,1)}ms`;
}

function inferenceCudaMemoryMetric(memory) {
  if (!memory?.available) return memory?.reason || 'CUDA unavailable';
  const devices = Array.isArray(memory.devices) ? memory.devices : [];
  if (!devices.length) return 'CUDA available · no visible device';
  return devices.map(device => {
    const gib = value => Number.isFinite(value) ? `${(Number(value) / 1024).toFixed(2)}GB` : '-';
    return `GPU${device.index ?? '-'} ${device.name || ''} · alloc ${gib(device.allocated_mib)} · reserved ${gib(device.reserved_mib)} · peak ${gib(device.peak_reserved_mib)} · free ${gib(device.free_mib)}/${gib(device.total_mib)}`;
  }).join(' | ');
}

function inferenceLifecycleMetric(lifecycle) {
  const state = String(lifecycle?.state || 'unknown').toUpperCase();
  return `${state} · accepting ${lifecycle?.accepting ? 'YES' : 'NO'} · inflight ${lifecycle?.inflight_requests ?? '-'} · peak ${lifecycle?.peak_inflight_requests ?? '-'} · drain rejects ${lifecycle?.rejected_during_drain_total ?? '-'}`;
}

async function loadInferenceTelemetry() {
  const el = ensureInferenceTelemetryElement();
  if (!el) return;
  try {
    const status = await api('/api/inference/status');
    const health = status?.live?.health;
    const serving = health?.serving;
    if (!status?.live?.running || !serving) {
      el.innerHTML = '<div><label>Serving Telemetry</label><strong>OFFLINE</strong></div>';
      if (status?.requested_serving) {
        syncInferenceTuning({
          micro_batch: {
            wait_ms: status.requested_serving.micro_batch_ms,
            max_rows: status.requested_serving.micro_batch_max_rows,
            max_pending_requests: status.requested_serving.max_pending_requests,
            request_deadline_ms: status.requested_serving.request_deadline_ms,
          },
          reload: {poll_ms: status.requested_serving.reload_poll_ms},
        });
      }
      return;
    }
    syncInferenceTuning(serving);
    const schedule = serving.micro_batch || {};
    const reload = serving.reload || {};
    const modes = serving.modes || {};
    const device = serving.device_scheduler || {};
    const cudaMemory = serving.cuda_memory || {};
    const lifecycle = serving.lifecycle || health?.lifecycle || {};
    const deadline = inferenceMetricNumber(schedule.request_deadline_ms, 0);
    const wait = inferenceMetricNumber(schedule.wait_ms, 1);
    const reloadState = reload.background ? 'BG reload ON' : 'BG reload OFF';
    el.innerHTML = [
      `<div><label>Scheduler</label><strong>${wait}ms merge · max ${schedule.max_rows ?? '-'} rows · pending ${schedule.max_pending_requests ?? '-'} · deadline ${deadline}ms</strong></div>`,
      `<div><label>Shared Device</label><strong>${inferenceDeviceMetric(device)}</strong></div>`,
      `<div><label>CUDA Memory</label><strong>${inferenceCudaMemoryMetric(cudaMemory)}</strong></div>`,
      `<div><label>Lifecycle</label><strong>${inferenceLifecycleMetric(lifecycle)}</strong></div>`,
      `<div><label>Reload</label><strong>${reloadState} · poll ${inferenceMetricNumber(reload.poll_ms, 0)}ms · quiet ${inferenceMetricNumber(reload.quiet_ms,0)}ms · wait ${inferenceMetricNumber(reload.wait_ms,0)}ms</strong></div>`,
      `<div><label>3P</label><strong>${inferenceModeMetric('3p', modes['3p'])}</strong></div>`,
      `<div><label>4P</label><strong>${inferenceModeMetric('4p', modes['4p'])}</strong></div>`,
    ].join('');
  } catch (e) {
    el.innerHTML = `<div><label>Serving Telemetry</label><strong>${e.message}</strong></div>`;
  }
}

let latestInferenceBenchmark = null;

function ensureInferenceBenchmarkControls() {
  let root = document.getElementById('inferenceBenchmark');
  if (root) return root;
  const telemetry = ensureInferenceTelemetryElement();
  if (!telemetry) return null;
  root = document.createElement('div');
  root.id = 'inferenceBenchmark';
  root.className = 'top-gap';
  root.innerHTML = [
    '<div class="form-grid">',
    '<label>Benchmark modes<select id="inferenceBenchmarkModes"><option value="both" selected>3P + 4P</option><option value="3p">3P only</option><option value="4p">4P only</option></select></label>',
    '<label>Requests / mode<input id="inferenceBenchmarkRequests" type="number" value="64" min="4" max="4096" step="4" /></label>',
    '<label>Concurrency<input id="inferenceBenchmarkConcurrency" type="number" value="8" min="1" max="256" step="1" /></label>',
    '<label>Rows / request<input id="inferenceBenchmarkRows" type="number" value="1" min="1" max="64" step="1" /></label>',
    '<label>Sweep waits (ms)<input id="inferenceSweepWaits" value="0,0.5,1,1.5,2" /></label>',
    '<label>Latency budget p95 (ms)<input id="inferenceLatencyBudget" type="number" value="100" min="1" max="1000" step="5" /></label>',
    '</div>',
    '<div class="button-row top-gap">',
    '<button class="secondary" onclick="startInferenceBenchmark(false)">현재 설정 Benchmark</button>',
    '<button class="secondary" onclick="startInferenceSweep()">Micro-batch A/B Sweep</button>',
    '<button class="secondary" onclick="loadInferenceBenchmark()">최신 Benchmark 결과</button>',
    '<button class="secondary" onclick="applyInferenceBenchmarkRecommendation()">추천값을 Tuning에 적용</button>',
    '</div>',
    '<div class="subtle top-gap">A/B Sweep는 loaded/compiled 모델을 유지한 채 micro-batch wait만 후보별로 live 변경하고 완료 후 원래 값을 복구합니다. 실제 대국 중에는 부하 측정을 실행하지 않는 것을 권장합니다.</div>',
    '<div id="inferenceBenchmarkResult" class="subtle top-gap">Benchmark 미실행</div>',
  ].join('');
  telemetry.insertAdjacentElement('afterend', root);
  return root;
}

function benchmarkModeText(mode, result) {
  if (!result) return `${mode.toUpperCase()} -`;
  const latency=result.latency_ms||{};
  return `${mode.toUpperCase()} p95 ${inferenceMetricNumber(latency.p95,1)}ms · ${inferenceMetricNumber(result.rows_per_s,1)} rows/s · GPU batch ${inferenceMetricNumber(result.observed_rows_per_execution,2)} · error ${(Number(result.error_rate||0)*100).toFixed(2)}%`;
}

function renderInferenceBenchmark(report, path='') {
  ensureInferenceBenchmarkControls();
  latestInferenceBenchmark=report||null;
  const el=document.getElementById('inferenceBenchmarkResult');
  if(!el) return;
  if(!report){ el.textContent='Benchmark 결과가 없습니다.'; return; }
  const rec=report.recommendation?.recommended||{};
  const reasons=(report.recommendation?.reasons||[]).join(' ');
  const modeText=[benchmarkModeText('3p',report.modes?.['3p']),benchmarkModeText('4p',report.modes?.['4p'])].filter(x=>!x.endsWith(' -')).join(' · ');
  const sweep=report.sweep;
  const sweepText=sweep ? ` · A/B winner ${sweep.winner_micro_batch_ms}ms · budget ${sweep.latency_budget_ms}ms · original restored ${sweep.original_restored?'YES':'NO'}` : '';
  el.textContent=`${modeText}${sweepText} · 추천 ${rec.micro_batch_ms ?? '-'}ms / max ${rec.micro_batch_max_rows ?? '-'} rows / pending ${rec.max_pending_requests ?? '-'} / deadline ${rec.request_deadline_ms ?? '-'}ms${reasons?` · ${reasons}`:''}${path?` · ${path}`:''}`;
}

function inferenceBenchmarkBody(sweep=false) {
  return {
    modes: document.getElementById('inferenceBenchmarkModes')?.value || 'both',
    requests_per_mode: inferenceNumber('inferenceBenchmarkRequests',64),
    concurrency: inferenceNumber('inferenceBenchmarkConcurrency',8),
    batch_rows: inferenceNumber('inferenceBenchmarkRows',1),
    sweep,
    sweep_waits: document.getElementById('inferenceSweepWaits')?.value || '0,0.5,1,1.5,2',
    latency_budget_ms: inferenceNumber('inferenceLatencyBudget',100),
  };
}

async function startInferenceBenchmark(sweep=false) {
  ensureInferenceBenchmarkControls();
  const body=inferenceBenchmarkBody(sweep);
  try {
    const j=await api('/api/inference/benchmark/start',{method:'POST',body:JSON.stringify(body)});
    selectedJob=j.id;
    await loadJobs();
    toast(`${sweep?'A/B sweep':'Serving benchmark'} 시작 · ${body.modes.toUpperCase()} · concurrency ${body.concurrency}`);
    return j;
  } catch(e){ toast(`Benchmark 시작 실패: ${e.message}`,true); throw e; }
}

async function startInferenceSweep() {
  return startInferenceBenchmark(true);
}

async function loadInferenceBenchmark() {
  ensureInferenceBenchmarkControls();
  try {
    const result=await api('/api/inference/benchmark/latest');
    if(!result.available){ renderInferenceBenchmark(null); return result; }
    renderInferenceBenchmark(result.report,result.path||'');
    return result;
  } catch(e){ toast(`Benchmark 결과: ${e.message}`,true); throw e; }
}

function applyInferenceBenchmarkRecommendation() {
  const rec=latestInferenceBenchmark?.recommendation?.recommended;
  if(!rec){ toast('먼저 완료된 benchmark 결과를 불러오세요.',true); return; }
  ensureInferenceTuningControls();
  const values={
    inferenceMicroBatchMs: rec.micro_batch_ms,
    inferenceMaxRows: rec.micro_batch_max_rows,
    inferenceMaxPending: rec.max_pending_requests,
    inferenceDeadlineMs: rec.request_deadline_ms,
    inferenceReloadPollMs: rec.reload_poll_ms,
  };
  for(const [id,value] of Object.entries(values)){
    const input=document.getElementById(id);
    if(input && Number.isFinite(Number(value))) input.value=String(value);
  }
  const tuning=document.getElementById('inferenceTuning');
  if(tuning) tuning.dataset.dirty='1';
  toast('Benchmark 추천값을 입력했습니다. Akagi API 시작/재시작을 눌러 적용하세요.');
}

window.startInferenceApi = startInferenceApi;
window.startInferenceBenchmark = startInferenceBenchmark;
window.startInferenceSweep = startInferenceSweep;
window.loadInferenceBenchmark = loadInferenceBenchmark;
window.applyInferenceBenchmarkRecommendation = applyInferenceBenchmarkRecommendation;
window.addEventListener('DOMContentLoaded', () => {
  ensureInferenceTuningControls();
  loadInferenceTelemetry();
  ensureInferenceBenchmarkControls();
  loadInferenceBenchmark();
  window.setInterval(loadInferenceTelemetry, 2500);
});
