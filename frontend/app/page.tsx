"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";

/** Empty env = same origin (Docker/nginx). Local dev defaults to :8000. */
function resolveApiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (env && env.length > 0) return env.replace(/\/$/, "");
  if (typeof window !== "undefined") return "";
  return "http://127.0.0.1:8000";
}
const API_BASE = resolveApiBase();

// DEMO_HIDE: flip to `false` to un-hide the ML-ops panels
// (Honest Performance Card + Data Drift Monitor).
// Typed as `boolean` so TypeScript keeps the runtime checks inside each block.
const DEMO_HIDE_OPS_PANELS: boolean = true;

interface QueueClaim {
  claim_id: string;
  claimant_name: string;
  policy_type: string;
  incident_type: string;
  days_open: number;
  total_claimed: number;
  state: string;
  risk_score_pct: number;
  is_high_risk: boolean;
}

interface QueueData {
  claims: QueueClaim[];
  total: number;
  high_risk_count: number;
  avg_risk: number;
  avg_days_open: number;
}

interface Metrics {
  status: string;
  split?: string;
  total_evaluated: number;
  threshold: number;
  confusion_matrix: { tp: number; fp: number; tn: number; fn: number };
  precision: number;
  recall: number;
  f1: number;
  accuracy: number;
  baseline_random_recall: number;
  notes: string;
}

interface ScenarioReport {
  n_features_used: number;
  roc_auc: number;
  average_precision: number;
  positive_rate: number;
  threshold_sweep: {
    threshold: number;
    tp: number; fp: number; tn: number; fn: number;
    precision: number; recall: number; f1: number;
  }[];
}

interface EvalReport {
  status: string;
  scenarios?: Record<string, ScenarioReport>;
  dropped_in_adversarial?: string[];
  split?: { train: number; holdout: number };
}

type RiskFilter = "all" | "high" | "medium" | "low";
type PlotName = "calibration_curve" | "pr_curve" | "lift_chart" | "confusion_matrices";

const PLOT_LABELS: Record<PlotName, string> = {
  calibration_curve: "Calibration",
  pr_curve: "Precision-Recall",
  lift_chart: "Cumulative Gains",
  confusion_matrices: "Confusion Matrices",
};

const SCENARIO_LABELS: Record<string, { label: string; note: string; tone: "emerald" | "sky" | "amber" }> = {
  full: {
    label: "Full pipeline",
    note: "All features (including NLP lexicon signals)",
    tone: "emerald",
  },
  adversarial_text: {
    label: "Adversarial text",
    note: "Trigger words masked in TF-IDF, lexicon features dropped",
    tone: "sky",
  },
  structured_only: {
    label: "Structured only",
    note: "No text model. Stress-test floor.",
    tone: "amber",
  },
};

interface HoldoutScores {
  n: number;
  claim_ids: string[];
  y_true: number[];
  y_pred_proba: number[];
}

interface FairnessRow {
  group: string;
  n: number;
  escalations: number;
  recall: number | null;
  precision: number | null;
  fpr: number | null;
  base_rate: number | null;
  recall_disparity_vs_overall: number;
}

interface DriftFeature {
  feature: string;
  psi: number;
  severity: "stable" | "moderate" | "significant";
  train_mean: number | null;
  current_mean: number | null;
  mean_delta_pct: number | null;
}

interface DriftReport {
  status: "stable" | "watch" | "drift_detected" | "no_split" | "unavailable";
  n_reference?: number;
  n_current?: number;
  reference_window?: string;
  current_window?: string;
  features?: DriftFeature[];
  notes?: string;
}

interface FairnessReport {
  status: string;
  threshold?: number;
  overall?: {
    n: number;
    recall: number | null;
    precision: number | null;
    base_rate: number | null;
  };
  slices?: Record<string, FairnessRow[]>;
  worst_recall_gap?: {
    attribute: string;
    group: string;
    gap: number;
    group_recall: number | null;
    overall_recall: number | null;
    n: number;
  } | null;
  notes?: string;
}

export default function ClaimsQueue() {
  const router = useRouter();
  const [data, setData] = useState<QueueData | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [evalReport, setEvalReport] = useState<EvalReport | null>(null);
  const [scores, setScores] = useState<HoldoutScores | null>(null);
  const [fairness, setFairness] = useState<FairnessReport | null>(null);
  const [fairnessSlice, setFairnessSlice] = useState<string>("state");
  const [drift, setDrift] = useState<DriftReport | null>(null);
  const [feedbackStats, setFeedbackStats] = useState<{
    total: number;
    disagreement_rate: number;
    agreement_rate: number;
    by_verdict: Record<string, number>;
    recent: any[];
    next_retrain_eta?: string;
  } | null>(null);
  const [sliderThreshold, setSliderThreshold] = useState<number>(50);
  // ROI calculator inputs — seeded from the dataset defaults
  const [avgClaimValue, setAvgClaimValue] = useState<number>(289000);
  const [escalationMultiplier, setEscalationMultiplier] = useState<number>(3.5);
  const [monthlyVolume, setMonthlyVolume] = useState<number>(500);
  const [activePlot, setActivePlot] = useState<PlotName>("calibration_curve");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const [policyFilter, setPolicyFilter] = useState<string>("all");
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [claimsRes, metricsRes, evalRes, scoresRes, fairRes, feedbackRes, driftRes] =
          await Promise.all([
            fetch(`${API_BASE}/claims`),
            fetch(`${API_BASE}/metrics`),
            fetch(`${API_BASE}/evaluation/report`),
            fetch(`${API_BASE}/metrics/holdout_scores`),
            fetch(`${API_BASE}/fairness?threshold=50`),
            fetch(`${API_BASE}/feedback/summary`),
            fetch(`${API_BASE}/drift`),
          ]);
        if (!claimsRes.ok) throw new Error("Failed to load claims queue");
        const claimsData: QueueData = await claimsRes.json();
        const metricsData: Metrics = await metricsRes.json();
        const evalData: EvalReport = evalRes.ok
          ? await evalRes.json()
          : { status: "missing" };
        const scoresData: HoldoutScores = scoresRes.ok
          ? await scoresRes.json()
          : { n: 0, claim_ids: [], y_true: [], y_pred_proba: [] };
        const fairData: FairnessReport = fairRes.ok
          ? await fairRes.json()
          : { status: "unavailable" };
        const fbData = feedbackRes.ok ? await feedbackRes.json() : null;
        const driftData: DriftReport = driftRes.ok
          ? await driftRes.json()
          : { status: "unavailable" };
        setData(claimsData);
        setMetrics(metricsData);
        setEvalReport(evalData);
        setScores(scoresData);
        setFairness(fairData);
        setFeedbackStats(fbData);
        setDrift(driftData);
        if (metricsData.threshold) setSliderThreshold(metricsData.threshold);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Derived ROI: escalations caught per month vs a random-flagging baseline.
  const roi = useMemo(() => {
    if (!scores || scores.n === 0) return null;
    const positiveRate = metrics?.baseline_random_recall ?? 0.35;
    const recall = (() => {
      let tp = 0, fn = 0;
      for (let i = 0; i < scores.n; i++) {
        const pred = scores.y_pred_proba[i] >= sliderThreshold ? 1 : 0;
        if (scores.y_true[i] === 1) {
          if (pred === 1) tp++;
          else fn++;
        }
      }
      return tp + fn > 0 ? tp / (tp + fn) : 0;
    })();
    const escalationsPerMonth = monthlyVolume * positiveRate;
    const caughtByModel = escalationsPerMonth * recall;
    const caughtByBaseline = escalationsPerMonth * positiveRate; // random flagging
    const earlyDetections = Math.max(0, caughtByModel - caughtByBaseline);
    const costPerMiss = avgClaimValue * (escalationMultiplier - 1);
    const monthlySavings = earlyDetections * costPerMiss;
    return {
      recall,
      escalationsPerMonth,
      caughtByModel,
      caughtByBaseline,
      earlyDetections,
      monthlySavings,
      annualSavings: monthlySavings * 12,
      costPerMiss,
    };
  }, [scores, sliderThreshold, avgClaimValue, escalationMultiplier, monthlyVolume, metrics]);

  // Live confusion matrix recomputed whenever the slider moves.
  const liveCM = useMemo(() => {
    if (!scores || scores.n === 0) return null;
    let tp = 0, fp = 0, tn = 0, fn = 0;
    for (let i = 0; i < scores.n; i++) {
      const pred = scores.y_pred_proba[i] >= sliderThreshold ? 1 : 0;
      const truth = scores.y_true[i];
      if (pred === 1 && truth === 1) tp++;
      else if (pred === 1 && truth === 0) fp++;
      else if (pred === 0 && truth === 0) tn++;
      else fn++;
    }
    const precision = tp + fp > 0 ? tp / (tp + fp) : 0;
    const recall = tp + fn > 0 ? tp / (tp + fn) : 0;
    const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;
    const accuracy = (tp + tn) / Math.max(tp + fp + tn + fn, 1);
    return { tp, fp, tn, fn, precision, recall, f1, accuracy };
  }, [scores, sliderThreshold]);

  const policyOptions = useMemo(() => {
    if (!data) return [];
    return Array.from(new Set(data.claims.map((c) => c.policy_type).filter(Boolean))).sort();
  }, [data]);

  const filteredClaims = useMemo(() => {
    if (!data) return [];
    return data.claims.filter((c) => {
      if (riskFilter === "high" && c.risk_score_pct < 70) return false;
      if (riskFilter === "medium" && (c.risk_score_pct < 40 || c.risk_score_pct >= 70)) return false;
      if (riskFilter === "low" && c.risk_score_pct >= 40) return false;
      if (policyFilter !== "all" && c.policy_type !== policyFilter) return false;
      if (
        searchTerm &&
        !c.claim_id.toLowerCase().includes(searchTerm.toLowerCase()) &&
        !c.claimant_name.toLowerCase().includes(searchTerm.toLowerCase())
      )
        return false;
      return true;
    });
  }, [data, riskFilter, policyFilter, searchTerm]);

  const openClaim = (id: string) => router.push(`/claim?id=${encodeURIComponent(id)}`);

  const riskTone = (pct: number) => {
  if (pct >= 60) return { bg: "bg-red-50", text: "text-red-700", dot: "bg-red-500", label: "HIGH" };
  if (pct >= 10) return { bg: "bg-amber-50", text: "text-amber-700", dot: "bg-amber-500", label: "MED" };
  return { bg: "bg-green-50", text: "text-green-700", dot: "bg-green-500", label: "LOW" };
};

  return (
    <>
      <header className="max-w-7xl mx-auto mb-8 pt-8 px-6 md:px-10">
        <h1 className="text-3xl font-black tracking-tight text-slate-900 mb-1">Triage Queue</h1>
        <p className="text-slate-500 font-medium">All open claims, ranked by escalation risk</p>
      </header>

      <div className="max-w-7xl mx-auto space-y-8 px-6 md:px-10 pb-16">
        {error && (
          <div className="p-4 bg-red-50 border border-red-200 text-red-600 rounded-2xl text-center font-medium">
            {error}
          </div>
        )}

        {data && (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <StatCard label="Total Claims" value={data.total.toString()} tone="blue" />
            <StatCard
              label="High Risk"
              value={data.high_risk_count.toString()}
              sub={`${((data.high_risk_count / data.total) * 100).toFixed(0)}% of queue`}
              tone="red"
            />
            <StatCard label="Avg Risk" value={`${data.avg_risk}%`} tone="amber" />
            <StatCard label="Avg Days Open" value={data.avg_days_open.toString()} tone="slate" />
            {feedbackStats && (
              <StatCard
                label="Adjuster Agreement"
                value={
                  feedbackStats.total > 0
                    ? `${((1 - feedbackStats.disagreement_rate) * 100).toFixed(0)}%`
                    : "—"
                }
                sub={
                  feedbackStats.total > 0
                    ? `${feedbackStats.total} verdicts · retrain ${feedbackStats.next_retrain_eta ?? ""}`
                    : "Awaiting first verdict"
                }
                tone="blue"
              />
            )}
          </div>
        )}

        {/* DEMO_HIDE: Honest Performance Card — flip DEMO_HIDE_OPS_PANELS to false (top of file) to show the scenario comparison + calibration/PR/lift plots. Keep the code, it's winner material. */}
        {!DEMO_HIDE_OPS_PANELS && evalReport && evalReport.status === "ok" && evalReport.scenarios && (
          <div className="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-sm font-black uppercase tracking-widest text-slate-500">
                  Holdout Evaluation — Honest Performance Card
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  {evalReport.split
                    ? `${evalReport.split.train} train / ${evalReport.split.holdout} held-out claims (frozen at training time)`
                    : "Held-out evaluation"}
                  . Full pipeline performs near-perfectly on this synthetic dataset — scenarios below
                  progressively strip signals to show realistic performance under stress.
                </p>
              </div>
              <span className="bg-sky-100 text-sky-700 text-[10px] font-black uppercase px-3 py-1 rounded-full border border-sky-200">
                Out-of-sample
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
              {Object.entries(evalReport.scenarios).map(([key, s]) => {
                const meta = SCENARIO_LABELS[key] || {
                  label: key,
                  note: "",
                  tone: "amber" as const,
                };
                const sweep = s.threshold_sweep.find((t) => t.threshold === 0.5) ||
                  s.threshold_sweep[0];
                const toneMap = {
                  emerald: "bg-emerald-50 border-emerald-200 text-emerald-700",
                  sky: "bg-sky-50 border-sky-200 text-sky-700",
                  amber: "bg-amber-50 border-amber-200 text-amber-700",
                };
                return (
                  <div
                    key={key}
                    className={`p-5 rounded-2xl border ${toneMap[meta.tone]}`}
                  >
                    <div className="text-[10px] font-black uppercase tracking-widest mb-1 opacity-80">
                      {meta.label}
                    </div>
                    <div className="text-3xl font-black">
                      {(sweep.recall * 100).toFixed(0)}%
                    </div>
                    <div className="text-[10px] font-bold uppercase opacity-70 mt-0.5">
                      Recall @ t=0.50
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-700">
                      <div>
                        <div className="opacity-60 uppercase text-[9px] font-bold">Precision</div>
                        <div className="font-black">{(sweep.precision * 100).toFixed(0)}%</div>
                      </div>
                      <div>
                        <div className="opacity-60 uppercase text-[9px] font-bold">ROC-AUC</div>
                        <div className="font-black">{s.roc_auc.toFixed(3)}</div>
                      </div>
                      <div>
                        <div className="opacity-60 uppercase text-[9px] font-bold">PR-AUC</div>
                        <div className="font-black">{s.average_precision.toFixed(3)}</div>
                      </div>
                      <div>
                        <div className="opacity-60 uppercase text-[9px] font-bold">Features</div>
                        <div className="font-black">{s.n_features_used}</div>
                      </div>
                    </div>
                    <p className="text-[10px] text-slate-600 mt-3 italic">{meta.note}</p>
                  </div>
                );
              })}
            </div>

            <div className="border-t border-slate-100 pt-5">
              <div className="flex flex-wrap gap-2 mb-4">
                {(Object.keys(PLOT_LABELS) as PlotName[]).map((p) => (
                  <button
                    key={p}
                    onClick={() => setActivePlot(p)}
                    className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase transition-all ${
                      activePlot === p
                        ? "bg-slate-900 text-white"
                        : "bg-slate-100 text-slate-500 hover:bg-slate-200"
                    }`}
                  >
                    {PLOT_LABELS[p]}
                  </button>
                ))}
              </div>
              <div className="bg-slate-50 rounded-2xl p-4 flex justify-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`${API_BASE}/evaluation/plot/${activePlot}`}
                  alt={PLOT_LABELS[activePlot]}
                  className="max-w-full h-auto rounded-lg"
                />
              </div>
              {evalReport.dropped_in_adversarial && evalReport.dropped_in_adversarial.length > 0 && (
                <p className="text-[10px] text-slate-400 mt-3 font-mono">
                  Features dropped in adversarial scenarios:{" "}
                  {evalReport.dropped_in_adversarial.join(", ")}
                </p>
              )}
            </div>
          </div>
        )}

        {roi && (
          <div className="bg-gradient-to-br from-emerald-900 via-emerald-800 to-teal-900 p-8 rounded-3xl shadow-xl text-white">
            <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <span className="text-2xl">💰</span>
                <div>
                  <h3 className="text-xl font-bold">Business Impact · ROI Calculator</h3>
                  <p className="text-xs text-emerald-200 mt-0.5">
                    Translates today's threshold ({sliderThreshold.toFixed(0)}%) and model
                    recall into monthly savings. Adjust assumptions to match your book.
                  </p>
                </div>
              </div>
              <span className="text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-full border bg-emerald-800/60 text-emerald-200 border-emerald-700">
                Live · threshold-linked
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              <ROIInput
                label="Claims / month"
                value={monthlyVolume}
                onChange={setMonthlyVolume}
                min={10}
                step={10}
                format={(v) => v.toLocaleString()}
              />
              <ROIInput
                label="Avg claim value"
                value={avgClaimValue}
                onChange={setAvgClaimValue}
                min={1000}
                step={5000}
                format={(v) => `$${v.toLocaleString()}`}
              />
              <ROIInput
                label="Escalated cost multiplier"
                value={escalationMultiplier}
                onChange={setEscalationMultiplier}
                min={1.2}
                step={0.1}
                format={(v) => `${v.toFixed(1)}×`}
              />
              <div className="bg-emerald-800/40 rounded-2xl p-4 border border-emerald-700">
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">
                  Current recall
                </div>
                <div className="text-2xl font-black text-white mt-1">
                  {(roi.recall * 100).toFixed(0)}%
                </div>
                <div className="text-[10px] text-emerald-300 mt-1">at slider threshold</div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white/10 rounded-2xl p-5 border border-white/20">
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200 mb-2">
                  Monthly savings
                </div>
                <div className="text-4xl font-black text-white">
                  ${Math.round(roi.monthlySavings / 1000).toLocaleString()}k
                </div>
                <div className="text-[11px] text-emerald-200 mt-2">
                  ~{roi.earlyDetections.toFixed(1)} escalations caught early vs random triage
                </div>
              </div>
              <div className="bg-white/10 rounded-2xl p-5 border border-white/20">
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200 mb-2">
                  Annual savings
                </div>
                <div className="text-4xl font-black text-white">
                  ${(roi.annualSavings / 1_000_000).toFixed(1)}M
                </div>
                <div className="text-[11px] text-emerald-200 mt-2">
                  Cost-per-miss: ${Math.round(roi.costPerMiss / 1000).toLocaleString()}k
                </div>
              </div>
              <div className="bg-white/10 rounded-2xl p-5 border border-white/20">
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200 mb-2">
                  Unit economics
                </div>
                <div className="space-y-1.5 text-[11px] text-emerald-100">
                  <div className="flex justify-between">
                    <span>Escalations expected / mo</span>
                    <span className="font-mono font-black">
                      {roi.escalationsPerMonth.toFixed(0)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Caught by model</span>
                    <span className="font-mono font-black">
                      {roi.caughtByModel.toFixed(1)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Caught by random triage</span>
                    <span className="font-mono font-black text-emerald-300">
                      {roi.caughtByBaseline.toFixed(1)}
                    </span>
                  </div>
                  <div className="flex justify-between pt-1.5 border-t border-white/20">
                    <span>Model lift</span>
                    <span className="font-mono font-black text-white">
                      +{roi.earlyDetections.toFixed(1)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* DEMO_HIDE: Data Drift Monitor (PSI) — flip DEMO_HIDE_OPS_PANELS to false (top of file) to show per-feature PSI tiles. */}
        {!DEMO_HIDE_OPS_PANELS && drift && drift.features && drift.features.length > 0 && (
          <div className="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
              <div>
                <h2 className="text-sm font-black uppercase tracking-widest text-slate-500">
                  Data Drift Monitor · PSI
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Population Stability Index per feature between training ({drift.n_reference})
                  and current ({drift.n_current}) distributions.
                </p>
              </div>
              <span
                className={`text-[10px] font-black uppercase px-3 py-1.5 rounded-full border ${
                  drift.status === "drift_detected"
                    ? "bg-red-100 text-red-700 border-red-200"
                    : drift.status === "watch"
                    ? "bg-amber-100 text-amber-800 border-amber-200"
                    : "bg-emerald-100 text-emerald-700 border-emerald-200"
                }`}
              >
                {drift.status === "drift_detected"
                  ? "⚠ Drift detected"
                  : drift.status === "watch"
                  ? "• Moderate"
                  : "✓ Stable"}
              </span>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
              {drift.features.slice(0, 12).map((f) => {
                const sevCls =
                  f.severity === "significant"
                    ? "bg-red-50 border-red-200 text-red-700"
                    : f.severity === "moderate"
                    ? "bg-amber-50 border-amber-200 text-amber-700"
                    : "bg-emerald-50 border-emerald-200 text-emerald-700";
                return (
                  <div
                    key={f.feature}
                    className={`p-3 rounded-xl border ${sevCls}`}
                    title={`train=${f.train_mean} · current=${f.current_mean}`}
                  >
                    <div className="text-[10px] font-mono truncate opacity-80">{f.feature}</div>
                    <div className="flex items-baseline justify-between">
                      <span className="text-sm font-black">{f.psi.toFixed(3)}</span>
                      {f.mean_delta_pct !== null && (
                        <span className="text-[10px] opacity-70">
                          Δ {f.mean_delta_pct > 0 ? "+" : ""}
                          {f.mean_delta_pct.toFixed(0)}%
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            {drift.notes && (
              <p className="text-[10px] text-slate-400 mt-3 italic">{drift.notes}</p>
            )}
          </div>
        )}

        {/* DEMO_HIDE: Production Model · Live Threshold Explorer + confusion matrix. Flip DEMO_HIDE_OPS_PANELS to false to restore. */}
        {!DEMO_HIDE_OPS_PANELS && metrics && metrics.status === "ok" && (
          <div className="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-sm font-black uppercase tracking-widest text-slate-500">
                  Production Model · Live Threshold Explorer
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  {metrics.split === "holdout" ? "Held-out" : "In-sample"} evaluation on{" "}
                  {metrics.total_evaluated} claims. Drag the threshold — the confusion matrix
                  below updates live, so you can see the precision/recall tradeoff.
                </p>
              </div>
              <span className="bg-emerald-100 text-emerald-700 text-[10px] font-black uppercase px-3 py-1 rounded-full border border-emerald-200">
                {metrics.split === "holdout" ? "Holdout" : "Production"}
              </span>
            </div>

            {scores && scores.n > 0 && (
              <div className="mb-6 p-4 bg-slate-50 border border-slate-200 rounded-2xl">
                <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">
                      Decision Threshold
                    </span>
                    <span className="text-lg font-black text-blue-700">
                      {sliderThreshold.toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex gap-2">
                    {[25, 50, 60, 75].map((v) => (
                      <button
                        key={v}
                        onClick={() => setSliderThreshold(v)}
                        className={`text-[10px] font-black uppercase px-2 py-1 rounded-lg border transition-all ${
                          Math.round(sliderThreshold) === v
                            ? "bg-blue-600 text-white border-blue-600"
                            : "bg-white text-slate-500 border-slate-200 hover:border-blue-300"
                        }`}
                      >
                        {v}%
                      </button>
                    ))}
                  </div>
                </div>
                <input
                  type="range"
                  min={1}
                  max={99}
                  step={1}
                  value={sliderThreshold}
                  onChange={(e) => setSliderThreshold(parseFloat(e.target.value))}
                  className="w-full accent-blue-600 cursor-pointer"
                />
                {liveCM && (
                  <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                    <LiveTile label="Recall" value={`${(liveCM.recall * 100).toFixed(1)}%`} tone="emerald" />
                    <LiveTile label="Precision" value={`${(liveCM.precision * 100).toFixed(1)}%`} tone="sky" />
                    <LiveTile label="F1" value={liveCM.f1.toFixed(3)} tone="slate" />
                    <LiveTile label="Escalations caught" value={`${liveCM.tp}/${liveCM.tp + liveCM.fn}`} tone="amber" />
                  </div>
                )}
              </div>
            )}

            <div className="mt-2 pt-2">
              <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-3">
                Confusion Matrix @ {sliderThreshold.toFixed(0)}% threshold
              </h3>
              <div className="grid grid-cols-3 gap-2 max-w-md text-center">
                <div></div>
                <div className="text-[10px] font-bold text-slate-400 uppercase">Pred: Escalate</div>
                <div className="text-[10px] font-bold text-slate-400 uppercase">Pred: Resolve</div>

                <div className="text-[10px] font-bold text-slate-400 uppercase self-center">
                  Actual: Esc
                </div>
                <div className="bg-emerald-100 text-emerald-800 font-black text-lg py-3 rounded-lg">
                  {liveCM ? liveCM.tp : metrics.confusion_matrix.tp}
                  <div className="text-[9px] font-medium">True Positive</div>
                </div>
                <div className="bg-red-100 text-red-800 font-black text-lg py-3 rounded-lg">
                  {liveCM ? liveCM.fn : metrics.confusion_matrix.fn}
                  <div className="text-[9px] font-medium">False Negative</div>
                </div>

                <div className="text-[10px] font-bold text-slate-400 uppercase self-center">
                  Actual: Res
                </div>
                <div className="bg-red-100 text-red-800 font-black text-lg py-3 rounded-lg">
                  {liveCM ? liveCM.fp : metrics.confusion_matrix.fp}
                  <div className="text-[9px] font-medium">False Positive</div>
                </div>
                <div className="bg-emerald-100 text-emerald-800 font-black text-lg py-3 rounded-lg">
                  {liveCM ? liveCM.tn : metrics.confusion_matrix.tn}
                  <div className="text-[9px] font-medium">True Negative</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* DEMO_HIDE: Fairness Audit · Recall by Segment. Flip DEMO_HIDE_OPS_PANELS to false to restore. */}
        {!DEMO_HIDE_OPS_PANELS && fairness && fairness.status === "ok" && fairness.slices && (
          <div className="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm">
            <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
              <div>
                <h2 className="text-sm font-black uppercase tracking-widest text-slate-500">
                  Fairness Audit · Recall by Segment
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Per-group recall at threshold {fairness.threshold}%. Overall recall:{" "}
                  <b className="text-slate-600">
                    {fairness.overall?.recall !== null
                      ? `${((fairness.overall?.recall ?? 0) * 100).toFixed(1)}%`
                      : "n/a"}
                  </b>{" "}
                  on {fairness.overall?.n} holdout claims.
                </p>
              </div>
              {fairness.worst_recall_gap && (
                <span
                  className={`text-[10px] font-black uppercase px-3 py-1.5 rounded-full border ${
                    fairness.worst_recall_gap.gap > 0.1
                      ? "bg-amber-100 text-amber-800 border-amber-200"
                      : "bg-emerald-100 text-emerald-700 border-emerald-200"
                  }`}
                >
                  Max gap: {(fairness.worst_recall_gap.gap * 100).toFixed(1)}pp ·{" "}
                  {fairness.worst_recall_gap.group} ({fairness.worst_recall_gap.attribute})
                </span>
              )}
            </div>

            <div className="flex gap-2 mb-4">
              {Object.keys(fairness.slices).map((sliceKey) => (
                <button
                  key={sliceKey}
                  onClick={() => setFairnessSlice(sliceKey)}
                  className={`text-[10px] font-black uppercase px-3 py-1.5 rounded-lg border transition-all ${
                    fairnessSlice === sliceKey
                      ? "bg-slate-900 text-white border-slate-900"
                      : "bg-white text-slate-500 border-slate-200 hover:border-slate-400"
                  }`}
                >
                  {sliceKey.replace("_", " ")}
                </button>
              ))}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-[10px] uppercase tracking-widest text-slate-500 font-black">
                  <tr>
                    <th className="text-left p-2">Group</th>
                    <th className="text-right p-2">N</th>
                    <th className="text-right p-2">Esc.</th>
                    <th className="text-right p-2">Base rate</th>
                    <th className="text-right p-2">Recall</th>
                    <th className="text-right p-2">Precision</th>
                    <th className="text-right p-2">Disparity</th>
                  </tr>
                </thead>
                <tbody>
                  {(fairness.slices[fairnessSlice] || []).map((r) => {
                    const disp = r.recall_disparity_vs_overall;
                    const bar = Math.max(0, Math.min(1, r.recall ?? 0));
                    const tone =
                      disp < -0.1
                        ? "text-red-600"
                        : disp < -0.05
                        ? "text-amber-600"
                        : disp > 0.05
                        ? "text-emerald-600"
                        : "text-slate-500";
                    return (
                      <tr
                        key={r.group}
                        className="border-t border-slate-100 hover:bg-slate-50"
                      >
                        <td className="p-2 font-bold text-slate-700">{r.group}</td>
                        <td className="p-2 text-right font-mono text-slate-600">{r.n}</td>
                        <td className="p-2 text-right font-mono text-slate-600">
                          {r.escalations}
                        </td>
                        <td className="p-2 text-right font-mono text-slate-500">
                          {r.base_rate !== null ? `${(r.base_rate * 100).toFixed(0)}%` : "—"}
                        </td>
                        <td className="p-2 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-16 h-1.5 bg-slate-100 rounded overflow-hidden">
                              <div
                                className={`h-full ${
                                  disp < -0.1
                                    ? "bg-red-500"
                                    : disp < -0.05
                                    ? "bg-amber-500"
                                    : "bg-emerald-500"
                                }`}
                                style={{ width: `${bar * 100}%` }}
                              />
                            </div>
                            <span className="font-mono font-black text-slate-700">
                              {r.recall !== null ? `${(r.recall * 100).toFixed(0)}%` : "—"}
                            </span>
                          </div>
                        </td>
                        <td className="p-2 text-right font-mono text-slate-600">
                          {r.precision !== null
                            ? `${(r.precision * 100).toFixed(0)}%`
                            : "—"}
                        </td>
                        <td className={`p-2 text-right font-mono font-black ${tone}`}>
                          {disp >= 0 ? "+" : ""}
                          {(disp * 100).toFixed(1)}pp
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {fairness.notes && (
              <p className="text-[10px] text-slate-400 mt-4 italic">{fairness.notes}</p>
            )}
          </div>
        )}

        <div className="bg-white p-5 rounded-3xl border border-slate-200 shadow-sm flex flex-wrap gap-3 items-center">
          <input
            placeholder="Search by claim ID or claimant..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="flex-1 min-w-[200px] px-4 py-2 rounded-xl bg-slate-50 border border-slate-200 outline-none focus:border-blue-400 text-sm"
          />
          <div className="flex p-1 bg-slate-100 rounded-xl">
            {(["all", "high", "medium", "low"] as RiskFilter[]).map((r) => (
              <button
                key={r}
                onClick={() => setRiskFilter(r)}
                className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase transition-all ${
                  riskFilter === r ? "bg-white text-blue-600 shadow-sm" : "text-slate-400"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          <select
            value={policyFilter}
            onChange={(e) => setPolicyFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-sm outline-none"
          >
            <option value="all">All Policies</option>
            {policyOptions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <span className="text-xs text-slate-500 font-medium">
            Showing {filteredClaims.length} of {data?.total ?? 0}
          </span>
        </div>

        <div className="bg-white rounded-3xl border border-slate-200 shadow-sm overflow-hidden">
          {loading ? (
            <div className="py-20 text-center text-slate-400 italic">Loading claims queue...</div>
          ) : filteredClaims.length === 0 ? (
            <div className="py-20 text-center text-slate-400 italic">
              No claims match your filters.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-[10px] uppercase tracking-widest text-slate-500 font-black">
                  <tr>
                    <th className="text-left p-4">Risk</th>
                    <th className="text-left p-4">Claim ID</th>
                    <th className="text-left p-4">Claimant</th>
                    <th className="text-left p-4">Policy</th>
                    <th className="text-left p-4">Incident</th>
                    <th className="text-right p-4">Claimed</th>
                    <th className="text-right p-4">Days</th>
                    <th className="text-right p-4"></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredClaims.map((c) => {
                    const tone = riskTone(c.risk_score_pct);
                    return (
                      <tr
                        key={c.claim_id}
                        onClick={() => openClaim(c.claim_id)}
                        className="border-t border-slate-100 hover:bg-blue-50/40 cursor-pointer transition-colors"
                      >
                        <td className="p-4">
                          <div className="flex items-center gap-3">
                            <span className={`w-2 h-2 rounded-full ${tone.dot}`}></span>
                            <div>
                              <div className={`font-black text-sm ${tone.text}`}>
                                {c.risk_score_pct.toFixed(1)}%
                              </div>
                              <div className={`text-[9px] font-bold ${tone.text} opacity-70`}>
                                {tone.label}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="p-4 font-mono text-xs text-slate-700">{c.claim_id}</td>
                        <td className="p-4 font-medium">{c.claimant_name}</td>
                        <td className="p-4 text-slate-600">{c.policy_type}</td>
                        <td className="p-4 text-slate-600">{c.incident_type}</td>
                        <td className="p-4 text-right font-mono text-slate-700">
                          ${c.total_claimed.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </td>
                        <td className="p-4 text-right text-slate-600">{c.days_open}</td>
                        <td className="p-4 text-right">
                          <span className="text-blue-500 text-lg">→</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone: "blue" | "red" | "amber" | "slate";
}) {
  const toneClass = {
    blue: "text-blue-600",
    red: "text-red-600",
    amber: "text-amber-600",
    slate: "text-slate-700",
  }[tone];
  return (
    <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
      <div className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-1">
        {label}
      </div>
      <div className={`text-3xl font-black ${toneClass}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function ROIInput({
  label,
  value,
  onChange,
  min,
  step,
  format,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  step: number;
  format: (v: number) => string;
}) {
  return (
    <div className="bg-emerald-800/40 rounded-2xl p-4 border border-emerald-700">
      <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300 mb-1">
        {label}
      </div>
      <div className="text-xl font-black text-white mb-2">{format(value)}</div>
      <input
        type="number"
        min={min}
        step={step}
        value={value}
        onChange={(e) => {
          const parsed = parseFloat(e.target.value);
          if (!Number.isNaN(parsed)) onChange(Math.max(min, parsed));
        }}
        className="w-full bg-emerald-950/40 border border-emerald-700 rounded-lg px-2 py-1 text-[11px] text-white outline-none focus:border-emerald-400 font-mono"
      />
    </div>
  );
}

function LiveTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "emerald" | "sky" | "slate" | "amber";
}) {
  const toneMap = {
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-700",
    sky: "bg-sky-50 border-sky-200 text-sky-700",
    slate: "bg-slate-50 border-slate-200 text-slate-700",
    amber: "bg-amber-50 border-amber-200 text-amber-700",
  };
  return (
    <div className={`p-3 rounded-xl border ${toneMap[tone]}`}>
      <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{label}</div>
      <div className="text-lg font-black mt-1">{value}</div>
    </div>
  );
}

function MetricTile({
  label,
  value,
  highlight,
  delta,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  delta?: string;
}) {
  return (
    <div
      className={`p-4 rounded-2xl border ${
        highlight ? "bg-emerald-50 border-emerald-200" : "bg-slate-50 border-slate-100"
      }`}
    >
      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-1">
        {label}
      </div>
      <div className={`text-2xl font-black ${highlight ? "text-emerald-700" : "text-slate-800"}`}>
        {value}
      </div>
      {delta && <div className="text-[10px] text-slate-500 mt-1">{delta}</div>}
    </div>
  );
}