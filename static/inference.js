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
    return result;
  } catch (e) {
    toast(`모델 reload 실패: ${e.message}`, true);
    await loadInference();
    throw e;
  }
}
