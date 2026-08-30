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
    const deadline = inferenceMetricNumber(schedule.request_deadline_ms, 0);
    const wait = inferenceMetricNumber(schedule.wait_ms, 1);
    const reloadState = reload.background ? 'BG reload ON' : 'BG reload OFF';
    el.innerHTML = [
      `<div><label>Scheduler</label><strong>${wait}ms merge · max ${schedule.max_rows ?? '-'} rows · pending ${schedule.max_pending_requests ?? '-'} · deadline ${deadline}ms</strong></div>`,
      `<div><label>Reload</label><strong>${reloadState} · poll ${inferenceMetricNumber(reload.poll_ms, 0)}ms</strong></div>`,
      `<div><label>3P</label><strong>${inferenceModeMetric('3p', modes['3p'])}</strong></div>`,
      `<div><label>4P</label><strong>${inferenceModeMetric('4p', modes['4p'])}</strong></div>`,
    ].join('');
  } catch (e) {
    el.innerHTML = `<div><label>Serving Telemetry</label><strong>${e.message}</strong></div>`;
  }
}

window.startInferenceApi = startInferenceApi;
window.addEventListener('DOMContentLoaded', () => {
  ensureInferenceTuningControls();
  loadInferenceTelemetry();
  window.setInterval(loadInferenceTelemetry, 2500);
});
