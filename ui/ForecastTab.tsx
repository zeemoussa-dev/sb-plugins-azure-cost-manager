import { useState } from 'react';
import { SeriesChart } from './charts';
import { saveScenario, type Analysis, type ScenarioSettings } from './client';
import { errorText, formatMoney, formatMonth } from './format';

const DEFAULT_SETTINGS: ScenarioSettings = {
  growth: { Base: 0.02, Upside: 0.035, Downside: 0.005 }, seasonality: true, active: 'Base', uplift_usd: 0, uplift_from: null,
};

function Fact({ label, value }: { label: string; value: string }) {
  return <><dt>{label}</dt><dd>{value}</dd></>;
}

function Automatic({ analysis }: { analysis: Analysis }) {
  const model = analysis.automatic_forecast;
  const currency = analysis.currency;
  if (!model) {
    return (
      <section className="card azure-cost-card">
        <h3>Automatic forecast</h3>
        <p className="text-muted">Six or more billed months are needed for a trend; sync more history.</p>
      </section>
    );
  }
  const trust = model.mape <= 0.1 ? 'good' : model.mape <= 0.25 ? 'fair' : 'weak';
  const hasPipeline = model.series.some((row) => row.pipeline);
  return (
    <section className="card azure-cost-card">
      <h3>Automatic forecast</h3>
      <p className="text-muted azure-cost-note">
        A straight-line trend fitted to the {model.months_of_history} billed months, times how each month of the year
        usually runs against it. Nothing to enter: it moves with the data.
      </p>
      <dl className="azure-cost-facts azure-cost-facts-wide">
        <Fact label="Next 12 months" value={formatMoney(model.next_12_months, currency)} />
        {hasPipeline ? <Fact label="…with the pipeline" value={formatMoney(model.next_12_months_with_pipeline, currency)} /> : null}
        <Fact label={`${model.next_year - 1}, actual + forecast`} value={formatMoney(model.this_year_total, currency)} />
        <Fact label={`${model.next_year} forecast`} value={`${formatMoney(model.next_year_total, currency)}${
          model.next_vs_this_pct != null ? ` (${model.next_vs_this_pct > 0 ? '+' : ''}${model.next_vs_this_pct}%)` : ''}`} />
        {hasPipeline ? <Fact label={`${model.next_year} with the pipeline`} value={formatMoney(model.next_year_with_pipeline, currency)} /> : null}
        <Fact label="Trend" value={`${formatMoney(model.slope, currency)} a month`} />
        <Fact label="Fit (R²)" value={String(model.r_squared)} />
        <Fact label="Backtest error (MAPE)" value={`${(model.mape * 100).toFixed(1)}% — ${trust}`} />
      </dl>
      <SeriesChart label="Actual against model and forecast" currency={currency} height={320}
                   categories={model.series.map((row) => row.month)} categoryLabel={(m) => formatMonth(m, true)}
                   series={[
                     { name: 'Actual', data: model.series.map((row) => row.actual), color: 0 },
                     { name: 'Forecast', data: model.series.map((row) => row.forecast), stack: 'ahead', color: 1 },
                     ...(hasPipeline ? [{ name: 'Pipeline', data: model.series.map((row) => row.forecast != null ? row.pipeline || null : null),
                       stack: 'ahead', color: 2 }] : []),
                     { name: 'Model', kind: 'line' as const, data: model.series.map((row) => row.model), color: 3 },
                   ]} />
    </section>
  );
}

function Scenarios({ analysis, onSaved }: { analysis: Analysis; onSaved: () => void }) {
  const scenarios = analysis.scenarios;
  const currency = analysis.currency;
  const [settings, setSettings] = useState<ScenarioSettings>(scenarios?.settings ?? analysis.customer.scenario ?? DEFAULT_SETTINGS);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!scenarios) return null;

  function growth(name: keyof ScenarioSettings['growth'], percent: string) {
    setSettings({ ...settings, growth: { ...settings.growth, [name]: Number(percent) / 100 } });
  }

  function save() {
    setSaving(true);
    setError(null);
    saveScenario(analysis.customer.id, settings).then(() => { setSaving(false); onSaved(); },
      (failure) => { setSaving(false); setError(errorText(failure)); });
  }

  return (
    <section className="card azure-cost-card">
      <h3>Scenarios</h3>
      <p className="text-muted azure-cost-note">
        Grows from {formatMonth(scenarios.base_month)} ({formatMoney(scenarios.base_total, currency)}) at a monthly rate per
        scenario. Saved for this customer and used in the export.
      </p>
      <div className="azure-cost-form-row">
        {(['Base', 'Upside', 'Downside'] as const).map((name) => (
          <label key={name} className="field-labeled">{name} growth, % a month
            <input type="number" step="0.1" value={Math.round(settings.growth[name] * 1000) / 10}
                   onChange={(event) => growth(name, event.target.value)} />
          </label>
        ))}
        <label className="field-labeled">Active scenario
          <select value={settings.active} onChange={(event) => setSettings({ ...settings, active: event.target.value as ScenarioSettings['active'] })}>
            <option>Base</option><option>Upside</option><option>Downside</option>
          </select>
        </label>
        <label className="field-labeled">Extra a month
          <input type="number" step="1000" value={settings.uplift_usd}
                 onChange={(event) => setSettings({ ...settings, uplift_usd: Number(event.target.value) })} />
        </label>
        <label className="field-labeled">…from
          <input type="month" value={settings.uplift_from ?? ''}
                 onChange={(event) => setSettings({ ...settings, uplift_from: event.target.value || null })} />
        </label>
      </div>
      <label className="azure-cost-check">
        <input type="checkbox" checked={settings.seasonality}
               onChange={(event) => setSettings({ ...settings, seasonality: event.target.checked })} />
        Apply the month-of-year pattern
      </label>
      <div className="azure-cost-toolbar">
        {error ? <span className="azure-cost-warning">{error}</span> : null}
        <button type="button" className="btn" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save and recalculate'}</button>
      </div>
      <dl className="azure-cost-facts azure-cost-facts-wide">
        {(['Base', 'Upside', 'Downside'] as const).map((name) => (
          <Fact key={name} label={`${name}, next year`} value={formatMoney(scenarios.next_year[name], currency)} />
        ))}
        {scenarios.pipeline_total ? <Fact label="Pipeline over the horizon" value={formatMoney(scenarios.pipeline_total, currency)} /> : null}
      </dl>
      <SeriesChart label="Scenarios" currency={currency} height={320}
                   categories={scenarios.rows.map((row) => row.month)} categoryLabel={(m) => formatMonth(m, true)}
                   series={[
                     { name: 'Upside', kind: 'line', data: scenarios.rows.map((row) => row.Upside), color: 2 },
                     { name: 'Base', kind: 'line', data: scenarios.rows.map((row) => row.Base), color: 0 },
                     { name: 'Downside', kind: 'line', data: scenarios.rows.map((row) => row.Downside), color: 5 },
                     ...(scenarios.pipeline_total ? [{ name: `${scenarios.settings.active} + pipeline`, kind: 'line' as const,
                       dashed: true, data: scenarios.rows.map((row) => row.active_with_pipeline), color: 1 }] : []),
                   ]} />
    </section>
  );
}

export function ForecastTab({ analysis, onChanged }: { analysis: Analysis; onChanged: () => void }) {
  return (
    <>
      <Automatic analysis={analysis} />
      <Scenarios key={analysis.customer.id} analysis={analysis} onSaved={onChanged} />
    </>
  );
}
