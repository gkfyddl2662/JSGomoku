function numberValue(id, fallback) {
  const raw = document.getElementById(id)?.value;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

async function startTrainingAblation(action='fresh') {
  const variant = document.getElementById('ablationVariant')?.value || 'rogs';
  const seed = Math.trunc(numberValue('ablationSeed', 0x9017));
  const args = {
    variant,
    seed,
    fresh: action === 'fresh',
    resume: action === 'resume',
    prepare_only: action === 'prepare',
  };
  try {
    await startJob('train_ablation', args);
    toast(`${currentMode().toUpperCase()} ${variant} ablation ${action === 'prepare' ? '설정 생성' : '학습 시작'}`);
  } catch (_) {
    // startJob already reports the backend error.
  }
}

function comparisonOptional(id) {
  return document.getElementById(id)?.value?.trim() || '';
}

async function startModelComparison() {
  const candidate = comparisonOptional('comparisonCandidate');
  const baseline = comparisonOptional('comparisonBaseline');
  if (!candidate || !baseline) {
    toast('Candidate와 Baseline checkpoint 상대경로를 모두 입력하세요.', true);
    return;
  }

  const args = {
    candidate,
    baseline,
    candidate_name: comparisonOptional('comparisonCandidateName'),
    baseline_name: comparisonOptional('comparisonBaselineName'),
    seed_start: Math.trunc(numberValue('comparisonSeedStart', 10000)),
    seed_count: Math.trunc(numberValue('comparisonSeedCount', 100)),
    seed_key: comparisonOptional('comparisonSeedKey') || '0xD5DFAA4CEF265CD7',
    device: comparisonOptional('comparisonDevice'),
    profile: comparisonOptional('comparisonProfile'),
    room: comparisonOptional('comparisonRoom'),
    rank: comparisonOptional('comparisonRank'),
    round_kind: comparisonOptional('comparisonRoundKind') || 'south',
    name: comparisonOptional('comparisonName'),
    fresh: document.getElementById('comparisonFresh')?.checked === true,
  };

  const compileMode = document.getElementById('comparisonCompile')?.value || 'inherit';
  if (compileMode === 'on') args.enable_compile = true;
  if (compileMode === 'off') args.enable_compile = false;
  const ampMode = document.getElementById('comparisonAmp')?.value || 'inherit';
  if (ampMode === 'on') args.enable_amp = true;
  if (ampMode === 'off') args.enable_amp = false;

  try {
    await startJob('model_compare', args);
    const gamesPerDirection = args.seed_count * (currentMode() === '3p' ? 3 : 4);
    toast(`양방향 모델 비교 시작 · 방향당 ${gamesPerDirection}게임`);
  } catch (_) {
    // startJob already reports the backend error.
  }
}

function fillComparisonFromPromotion() {
  const candidate = document.getElementById('promotionCandidate')?.value || '';
  if (candidate) {
    document.getElementById('comparisonCandidate').value = candidate;
    toast(`비교 Candidate에 복사: ${candidate}`);
  } else {
    toast('먼저 CHECKPOINTS에서 승격 후보를 선택하거나 Candidate를 입력하세요.', true);
  }
}
