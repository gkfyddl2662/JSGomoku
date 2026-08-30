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
      return;
    }
    const schedule = serving.micro_batch || {};
    const reload = serving.reload || {};
    const modes = serving.modes || {};
    const deadline = inferenceMetricNumber(schedule.request_deadline_ms, 0);
    const wait = inferenceMetricNumber(schedule.wait_ms, 1);
    const reloadState = reload.background ? 'BG reload ON' : 'BG reload OFF';
    el.innerHTML = [
      `<div><label>Scheduler</label><strong>${wait}ms merge · max ${schedule.max_rows ?? '-'} rows · deadline ${deadline}ms</strong></div>`,
      `<div><label>Reload</label><strong>${reloadState} · poll ${inferenceMetricNumber(reload.poll_ms, 0)}ms</strong></div>`,
      `<div><label>3P</label><strong>${inferenceModeMetric('3p', modes['3p'])}</strong></div>`,
      `<div><label>4P</label><strong>${inferenceModeMetric('4p', modes['4p'])}</strong></div>`,
    ].join('');
  } catch (e) {
    el.innerHTML = `<div><label>Serving Telemetry</label><strong>${e.message}</strong></div>`;
  }
}

// app.js owns the primary status refresh. Telemetry is deliberately independent so
// UI polling can be added without changing Akagi/API lifecycle code.
window.addEventListener('DOMContentLoaded', () => {
  loadInferenceTelemetry();
  window.setInterval(loadInferenceTelemetry, 2500);
});
