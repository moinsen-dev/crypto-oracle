const root = document.querySelector('[data-benchmark]');
if (root) {
  const results = JSON.parse(root.dataset.results);
  const asset = root.querySelector('#benchmark-asset');
  const horizon = root.querySelector('#benchmark-horizon');
  const names = { BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana' };
  const text = (selector, value) => { root.querySelector(selector).textContent = value; };
  function update() {
    const row = results.find(value => value.asset === asset.value && value.horizon === Number(horizon.value));
    if (!row) return;
    text('[data-chart-title]', `${names[row.asset]} · ${row.horizon} hours`);
    text('#error-chart-title', `${names[row.asset]}, ${row.horizon}-hour forecast error`);
    text('#error-chart-desc', `TimesFM error ${row.modelError.toFixed(3)}. Last-price baseline error ${row.baselineError.toFixed(3)}. Lower is better.`);
    for (const kind of ['model', 'baseline']) {
      const error = row[`${kind}Error`];
      root.querySelector(`[data-${kind}-bar]`).setAttribute('width', String(error * 82));
      root.querySelector(`[data-${kind}-value]`).setAttribute('x', String(154 + error * 82));
      text(`[data-${kind}-value]`, error.toFixed(3));
    }
    text('[data-relative-error]', `+${((row.modelError / row.baselineError - 1) * 100).toFixed(1)}%`);
    text('[data-coverage]', `${row.coverage.toFixed(1)}%`);
  }
  asset.addEventListener('change', update);
  horizon.addEventListener('change', update);
}
