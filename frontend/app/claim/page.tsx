"use client";

import { useState, useMemo, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";

function resolveApiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (env && env.length > 0) return env.replace(/\/$/, "");
  if (typeof window !== "undefined") return "";
  return "http://127.0.0.1:8000";
}
const API_BASE = resolveApiBase();

// DEMO_HIDE: flip to `false` to un-hide the Audit Trail panel.
// Typed as `boolean` so TypeScript keeps the runtime checks inside the block.
const DEMO_HIDE_OPS_PANELS: boolean = true;

type ModelKey = "groq_llama" | "google_gemini";
type Severity = "critical" | "high" | "medium" | "low";
type EmailKey = "groq" | "gemini";

interface LegalPrecedent {
  docid: string;
  title: string;
  headline: string;
  jurisdiction: string;
  url: string;
  match_query?: string;
}

interface CommunicationAudit {
  incident_description: string;
  adjuster_notes: string;
  email_transcript: string;
}

interface TriggerMatch {
  phrase: string;
  start: number;
  end: number;
  severity: Severity;
}

interface TriggerAnalysis {
  phrases: { phrase: string; severity: Severity }[];
  email_matches: TriggerMatch[];
  adjuster_matches: TriggerMatch[];
  source: "precomputed" | "dynamic" | "hybrid";
  risk_weight: number;
}

interface ConsensusAnalysis {
  status:
    | "strong_agreement"
    | "model_consensus"
    | "disagreement"
    | "single_model"
    | "single_model_disagree"
    | "ml_only"
    | "insufficient_data";
  agreement: boolean;
  message: string;
  signals: { groq: string; gemini: string; ml_model: string };
}

interface EmailDraft {
  subject?: string;
  body?: string;
  model?: string;
  error?: string;
}

interface NextActionEmails {
  groq?: EmailDraft;
  gemini?: EmailDraft;
}

interface Metrics {
  status: string;
  recall: number;
  precision: number;
  f1: number;
  total_evaluated: number;
}

interface Timeline {
  predicted_escalation_day: number;
  current_days_open: number | null;
  days_remaining: number | null;
  mae_days: number;
  holdout_r2: number | null;
  label: string;
  n_training_claims: number | null;
}

interface SimilarNeighbour {
  claim_id: string;
  similarity: number;
  outcome: string;
  days_open: number | null;
  total_claimed: number | null;
  approved_amount: number | null;
  incident_type: string;
  policy_type: string;
}

interface SimilarClaims {
  query_claim_id: string;
  neighbours: SimilarNeighbour[];
  escalated_in_top_k: number;
  top_k: number;
  escalation_rate_in_neighbourhood: number;
}

interface Grounding {
  citations_found: string[];
  unsupported_citations: string[];
  temperature: number;
  allowed_cases: string[];
}

interface CalibrationInfo {
  raw_ml_score: number;
  structured_calibrated: number;
  unstructured_score: number;
  method: string;
  weights: { structured: number; unstructured: number };
  final: number;
}

interface ClaimRecord {
  target_outcome?: string | null;
  claim_status?: string | null;
  action_status?: string | null;
  payment_status?: string | null;
  approved_amount?: number | null;
  total_claimed?: number | null;
  claimant_name?: string | null;
  days_open?: number | null;
  is_historical?: boolean;
}

interface AdjusterVerdict {
  verdict: "agree" | "disagree_too_high" | "disagree_too_low" | null;
  locked: boolean;
  stale: boolean;
  model_score_at_verdict?: number | null;
  current_model_score?: number | null;
  created_at?: string | null;
  id?: number | null;
}

interface RiskData {
  claim_id: string;
  adjuster_verdict?: AdjusterVerdict;
  source?: "dataset" | "salesforce" | "demo";
  salesforce_case_id?: string;
  salesforce_case_number?: string;
  claim_record?: ClaimRecord;
  ml_analysis: {
    claim_id: string;
    risk_score_pct: number;
    is_high_risk: boolean;
    top_warning_signs: string[];
    model_a_contribution?: number;
    model_b_contribution?: number;
    calibration?: CalibrationInfo;
  };
  timeline?: Timeline | null;
  similar_claims?: SimilarClaims | null;
  legal_context: {
    incident_type: string;
    precedents: LegalPrecedent[];
    us_search_status?: "ok" | "no_key" | "error" | "empty";
    india_search_status?: "ok" | "error" | "empty";
    us_spotlight_description?: string | null;
    us_spotlight_relevance?: string | null;
    matched_query?: string | null;
  };
  ai_consensus: {
    google_gemini?: string;
    groq_llama?: string;
    google_gemini_grounding?: Grounding | null;
    groq_llama_grounding?: Grounding | null;
  };
  consensus_analysis?: ConsensusAnalysis;
  communication_audit?: CommunicationAudit | null;
  trigger_analysis?: TriggerAnalysis | null;
  next_action_emails?: NextActionEmails;
  recommended_actions?: { steps: string[]; source?: string };
}

const MODEL_META: Record<ModelKey, { label: string; activeClass: string; dotClass: string }> = {
  groq_llama: {
    label: "Groq Llama 3.1",
    activeClass: "bg-green-100 text-green-700 border-green-300",
    dotClass: "bg-green-500",
  },
  google_gemini: {
    label: "Gemini 2.5",
    activeClass: "bg-blue-100 text-blue-700 border-blue-300",
    dotClass: "bg-blue-500",
  },
};

const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "bg-red-200 text-red-900 border-b-2 border-red-500",
  high: "bg-orange-200 text-orange-900 border-b-2 border-orange-500",
  medium: "bg-amber-200 text-amber-900 border-b-2 border-amber-500",
  low: "bg-yellow-200 text-yellow-900 border-b-2 border-yellow-500",
};

// 3-tier risk coloring: 0-10 green, 10-60 yellow, 60+ red
type RiskTier = "low" | "medium" | "high";

const getRiskTier = (pct: number): RiskTier => {
  if (pct < 10) return "low";
  if (pct < 60) return "medium";
  return "high";
};

const RISK_TIER_THEMES = {
  low: {
    probBg: "bg-green-50",
    probBorder: "border-green-200",
    probNumber: "text-green-600",
    probLabel: "text-green-700",
    probTagBg: "bg-green-100 text-green-700 border-green-200",
    probTagLabel: "LOW RISK",
    actionBg: "bg-gradient-to-br from-emerald-600 to-green-700",
    actionAccent: "text-green-200",
    actionBulletBg: "bg-white/15",
    actionBulletBorder: "border-white/10",
    actionBullet: "text-green-200",
    audAccent: "border-green-200 bg-green-50/30",
    audBadgeBg: "bg-green-100 text-green-700 border-green-200",
    audLabel: "LOW ESCALATION",
    audDot: "bg-green-500",
    audCardBorder: "border-green-100",
    audCardTitle: "text-green-700",
  },
  medium: {
    probBg: "bg-amber-50",
    probBorder: "border-amber-200",
    probNumber: "text-amber-600",
    probLabel: "text-amber-700",
    probTagBg: "bg-amber-100 text-amber-800 border-amber-200",
    probTagLabel: "MEDIUM RISK",
    actionBg: "bg-gradient-to-br from-amber-500 to-orange-600",
    actionAccent: "text-amber-100",
    actionBulletBg: "bg-white/15",
    actionBulletBorder: "border-white/10",
    actionBullet: "text-amber-100",
    audAccent: "border-amber-200 bg-amber-50/30",
    audBadgeBg: "bg-amber-100 text-amber-800 border-amber-200",
    audLabel: "MEDIUM ESCALATION",
    audDot: "bg-amber-500",
    audCardBorder: "border-amber-100",
    audCardTitle: "text-amber-700",
  },
  high: {
    probBg: "bg-red-50",
    probBorder: "border-red-200",
    probNumber: "text-red-600",
    probLabel: "text-red-700",
    probTagBg: "bg-red-100 text-red-700 border-red-200",
    probTagLabel: "HIGH RISK",
    actionBg: "bg-gradient-to-br from-red-600 to-red-700",
    actionAccent: "text-red-200",
    actionBulletBg: "bg-white/15",
    actionBulletBorder: "border-white/10",
    actionBullet: "text-red-200",
    audAccent: "border-red-200 bg-red-50/30",
    audBadgeBg: "bg-red-100 text-red-700 border-red-200",
    audLabel: "HIGH ESCALATION",
    audDot: "bg-red-500",
    audCardBorder: "border-red-100",
    audCardTitle: "text-red-700",
  },
};

// Consensus signal helpers
const signalStyle = (sig: string) => {
  if (sig === "UNAVAILABLE") return "text-slate-400 italic text-[10px]";
  if (sig === "HIGH") return "text-red-700";
  if (sig === "LOW") return "text-green-700";
  return "text-amber-700"; // MEDIUM
};

const signalDisplay = (sig: string) => (sig === "UNAVAILABLE" ? "N/A" : sig);

const extractStrategicAction = (markdown: string | undefined): string[] => {
  if (!markdown) return [];
  const patterns = [
    /(?:\*\*)?Strategic Action(?: Plan)?(?:\*\*)?\s*:?\s*([\s\S]*?)(?=\n\s*(?:\*\*)?[A-Z][A-Za-z ]{2,40}(?:\*\*)?\s*:|$)/i,
    /(?:\*\*)?Recommended Next Step(?:s)?(?:\*\*)?\s*:?\s*([\s\S]*?)(?=\n\s*(?:\*\*)?[A-Z][A-Za-z ]{2,40}(?:\*\*)?\s*:|$)/i,
  ];
  for (const regex of patterns) {
    const match = markdown.match(regex);
    if (!match?.[1]?.trim()) continue;
    let actionText = match[1].trim();
    if (/(^|\n)\s*[-*•]\s+/.test(actionText) || /^\d+[.)]\s+/m.test(actionText)) {
      return actionText
        .split(/\n+/)
        .map((l) =>
          l
            .replace(/^\s*\d+[.)]\s+/, "")
            .replace(/^\s*[-*•]\s+/, "")
            .replace(/\*\*(.+?)\*\*\s*:?/g, "$1:")
            .trim()
        )
        .filter((l) => l.length > 10);
    }
    const sentences = actionText
      .split(/(?<=[.!?])\s+(?=[A-Z])/)
      .map((s) => s.replace(/\*\*/g, "").trim())
      .filter((s) => s.length > 15);
    if (sentences.length) return sentences;
  }
  return [];
};

const looksLikeError = (text: string | undefined): boolean => {
  if (!text) return false;
  const lower = text.toLowerCase();
  return (
    lower.includes("error:") ||
    lower.includes("gemini error") ||
    lower.includes("key missing") ||
    lower.includes("404") ||
    lower.includes("is not found") ||
    lower.includes("is not supported")
  );
};

/** Gemini 2.5 can return a one-line stub when thinking ate the token budget (fixed server-side). */
const looksLikeTruncatedBrief = (text: string | undefined): boolean => {
  if (!text || looksLikeError(text)) return false;
  if (text.length < 160) return true;
  const lower = text.toLowerCase();
  const hasSections =
    lower.includes("legal impact") || lower.includes("recommended");
  return !hasSections;
};

function renderHighlighted(text: string, matches: TriggerMatch[]) {
  if (!matches || matches.length === 0) return <>{text}</>;
  const sorted = [...matches].sort((a, b) => a.start - b.start);
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((m, i) => {
    if (m.start > cursor) parts.push(<span key={`t-${i}`}>{text.slice(cursor, m.start)}</span>);
    parts.push(
      <mark
        key={`m-${i}`}
        className={`rounded px-0.5 font-semibold ${SEVERITY_STYLE[m.severity]}`}
        title={`Trigger phrase · ${m.severity.toUpperCase()} severity`}
      >
        {text.slice(m.start, m.end)}
      </mark>
    );
    cursor = m.end;
  });
  if (cursor < text.length) parts.push(<span key="tail">{text.slice(cursor)}</span>);
  return <>{parts}</>;
}

function RiskDashboard() {
  const searchParams = useSearchParams();
  const [claimId, setClaimId] = useState("CLM-2022-10461");
  const [data, setData] = useState<RiskData | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeRegion, setActiveRegion] = useState<"US" | "India">("US");
  const [activeModel, setActiveModel] = useState<ModelKey>("groq_llama");
  const [activeEmail, setActiveEmail] = useState<EmailKey>("groq");
  const [copied, setCopied] = useState(false);
  const [feedbackState, setFeedbackState] = useState<{
    submitting: boolean;
    message: string | null;
    last: string | null;
    locked: boolean;
    stale: boolean;
  }>({ submitting: false, message: null, last: null, locked: false, stale: false });

  const applySavedVerdict = (v?: AdjusterVerdict) => {
    if (!v?.verdict) {
      setFeedbackState((s) => ({
        ...s,
        last: null,
        locked: false,
        stale: false,
        message: null,
      }));
      return;
    }
    setFeedbackState((s) => ({
      ...s,
      last: v.verdict,
      locked: Boolean(v.locked),
      stale: Boolean(v.stale),
      message: v.stale
        ? `Risk score changed (${v.model_score_at_verdict?.toFixed(1)}% → ${v.current_model_score?.toFixed(1)}%) — please confirm your verdict again.`
        : `Saved verdict · recorded at ${v.model_score_at_verdict?.toFixed(1)}% risk`,
    }));
  };

  useEffect(() => {
    fetch(`${API_BASE}/metrics`)
      .then((r) => r.json())
      .then(setMetrics)
      .catch(() => {});
  }, []);

  const fetchAnalysis = async (idOverride?: string) => {
    const target = (idOverride ?? claimId).trim();
    if (!target) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/predict/${target}`);
      if (!res.ok) throw new Error("Claim ID not found or backend connection failed.");
      const result: RiskData = await res.json();
      if (!result.legal_context.precedents) result.legal_context.precedents = [];
      setData(result);
      applySavedVerdict(result.adjuster_verdict);
      const hasUS = result.legal_context.precedents.some((p) => p.jurisdiction?.toUpperCase() === "US");
      const hasIndia = result.legal_context.precedents.some((p) => p.jurisdiction?.toLowerCase() === "india");
      if (hasUS) setActiveRegion("US");
      else if (hasIndia) setActiveRegion("India");
      else setActiveRegion("US");
    } catch (err: any) {
      setError(err.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const queryClaim = searchParams.get("id");
    if (queryClaim) {
      setClaimId(queryClaim);
      fetchAnalysis(queryClaim);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    if (!data) return;
    const groqOk = data.ai_consensus.groq_llama && !looksLikeError(data.ai_consensus.groq_llama);
    const geminiOk = data.ai_consensus.google_gemini && !looksLikeError(data.ai_consensus.google_gemini);
    if (groqOk) setActiveModel("groq_llama");
    else if (geminiOk) setActiveModel("google_gemini");

    const groqEmailOk = data.next_action_emails?.groq?.body && !data.next_action_emails?.groq?.error;
    const geminiEmailOk = data.next_action_emails?.gemini?.body && !data.next_action_emails?.gemini?.error;
    if (groqEmailOk) setActiveEmail("groq");
    else if (geminiEmailOk) setActiveEmail("gemini");
  }, [data]);

  const filteredPrecedents = useMemo(() => {
    if (!data?.legal_context?.precedents) return [];
    return data.legal_context.precedents.filter(
      (p) => p.jurisdiction?.toLowerCase() === activeRegion.toLowerCase()
    );
  }, [data, activeRegion]);

  const usSpotlight = useMemo(
    () => data?.legal_context?.precedents?.find((p) => p.jurisdiction?.toUpperCase() === "US"),
    [data]
  );

  const strategicActionPoints = useMemo(() => {
    if (!data) return [];
    if (data.recommended_actions?.steps?.length) {
      return data.recommended_actions.steps;
    }
    const fromBrief = extractStrategicAction(data.ai_consensus[activeModel]);
    if (fromBrief.length) return fromBrief;
    return extractStrategicAction(
      data.ai_consensus.groq_llama || data.ai_consensus.google_gemini
    );
  }, [data, activeModel]);

  const activeModelText = data?.ai_consensus[activeModel];
  const activeModelHasError = looksLikeError(activeModelText);
  const activeModelTruncated = looksLikeTruncatedBrief(activeModelText);
  const availableModels: ModelKey[] = (["groq_llama", "google_gemini"] as ModelKey[]).filter((k) =>
    Boolean(data?.ai_consensus[k])
  );

  const activeEmailDraft = data?.next_action_emails?.[activeEmail];
  const availableEmails: EmailKey[] = (["groq", "gemini"] as EmailKey[]).filter((k) =>
    Boolean(data?.next_action_emails?.[k])
  );

  const submitFeedback = async (verdict: "agree" | "disagree_too_high" | "disagree_too_low") => {
    if (!data) return;
    setFeedbackState((s) => ({ ...s, submitting: true, message: null }));
    try {
      const res = await fetch(`${API_BASE}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claim_id: data.claim_id,
          verdict,
          model_score: data.ml_analysis.risk_score_pct,
          adjuster_id: "demo_adjuster",
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      if (typeof window !== "undefined") {
        sessionStorage.setItem("riskradar_feedback_updated", String(Date.now()));
      }
      setFeedbackState({
        submitting: false,
        last: verdict,
        locked: true,
        stale: false,
        message: `Saved · id=${body.id} · locked until risk score changes`,
      });
      applySavedVerdict({
        verdict,
        locked: true,
        stale: false,
        model_score_at_verdict: data.ml_analysis.risk_score_pct,
        current_model_score: data.ml_analysis.risk_score_pct,
      });
    } catch (err: any) {
      setFeedbackState({
        submitting: false,
        last: null,
        locked: false,
        stale: false,
        message: `Error: ${err.message}`,
      });
    }
  };

  const copyEmail = async () => {
    if (!activeEmailDraft?.body) return;
    const full = `Subject: ${activeEmailDraft.subject || ""}\n\n${activeEmailDraft.body}`;
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  // Three-tier risk theming based on actual score, not just is_high_risk
  const riskScore = data?.ml_analysis?.risk_score_pct ?? 0;
  const riskTier = getRiskTier(riskScore);
  const riskTheme = RISK_TIER_THEMES[riskTier];

  const emptyStateMessage = () => {
    if (!data) return "";
    if (activeRegion === "US") {
      switch (data.legal_context.us_search_status) {
        case "no_key":
          return "US legal search is not configured.";
        case "error":
          return "US legal search currently unavailable.";
        default:
          return "No US precedents identified for this claim.";
      }
    }
    return data.legal_context.india_search_status === "error"
      ? "India legal search unavailable."
      : "No India precedents identified.";
  };

  const audit = data?.communication_audit;
  const hasAnyAudit = !!(
    audit &&
    (audit.incident_description || audit.adjuster_notes || audit.email_transcript)
  );

  const consensus = data?.consensus_analysis;
  const consensusBadge = consensus
    ? consensus.status === "strong_agreement"
      ? { bg: "bg-emerald-100 text-emerald-700 border-emerald-300", label: "STRONG CONSENSUS", icon: "✓" }
      : consensus.status === "model_consensus"
      ? { bg: "bg-blue-100 text-blue-700 border-blue-300", label: "MODEL AGREEMENT", icon: "✓" }
      : consensus.status === "disagreement"
      ? { bg: "bg-amber-100 text-amber-800 border-amber-300", label: "MODELS DISAGREE", icon: "⚠" }
      : consensus.status === "single_model"
      ? { bg: "bg-blue-100 text-blue-700 border-blue-300", label: "PARTIAL CONSENSUS", icon: "✓" }
      : consensus.status === "single_model_disagree"
      ? { bg: "bg-amber-100 text-amber-800 border-amber-300", label: "PARTIAL DISAGREE", icon: "⚠" }
      : consensus.status === "ml_only"
      ? { bg: "bg-slate-100 text-slate-600 border-slate-300", label: "ML ONLY", icon: "ℹ" }
      : { bg: "bg-slate-100 text-slate-600 border-slate-300", label: "INSUFFICIENT DATA", icon: "?" }
    : null;

  return (
    <>
      <header className="max-w-7xl mx-auto mb-8 pt-8 px-6 md:px-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <h1 className="text-3xl font-black tracking-tight text-slate-900 mb-1">
            Single Claim Analysis
          </h1>
          <p className="text-slate-500 font-medium">
            Deep-dive risk intelligence for an individual claim
          </p>
          {data?.source === "salesforce" && (
            <div className="mt-2 inline-flex items-center gap-2 text-[11px] text-[#0176D3] bg-[#E8F4FD] border border-[#B4D9F5] rounded-full px-3 py-1 font-bold">
              Salesforce Case
              {(data.salesforce_case_number || data.salesforce_case_id) && (
                <span className="font-mono font-normal opacity-80">
                  {data.salesforce_case_number || data.salesforce_case_id}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-3 bg-white p-2 rounded-2xl shadow-sm border border-slate-200">
          <input
            className="bg-transparent px-4 py-2 outline-none w-48 md:w-64 text-slate-700"
            placeholder="Enter Claim ID..."
            value={claimId}
            onChange={(e) => setClaimId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fetchAnalysis()}
          />
          <button
            onClick={() => fetchAnalysis()}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-xl font-bold transition-all shadow-md shadow-blue-200 disabled:opacity-60"
          >
            {loading ? "Analyzing..." : "Run Analysis"}
          </button>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 md:px-10 pb-16">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-600 rounded-2xl text-center font-medium">
            {error}
          </div>
        )}

        {data ? (
          <div className="space-y-8 animate-in fade-in duration-500">
            <div className="grid grid-cols-12 gap-8">
              {/* LEFT COLUMN */}
              <div className="col-span-12 lg:col-span-4 space-y-6">
                {/* ESCALATION PROBABILITY */}
                <div
                  className={`${riskTheme.probBg} p-8 rounded-3xl shadow-sm border-2 ${riskTheme.probBorder} text-center`}
                >
                  <div className="flex items-center justify-between mb-6">
                    <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest">
                      Escalation Probability
                    </h3>
                    <span
                      className={`text-[9px] font-black uppercase px-2.5 py-1 rounded-full border ${riskTheme.probTagBg}`}
                    >
                      {riskTheme.probTagLabel}
                    </span>
                  </div>
                  <div className={`text-6xl font-black ${riskTheme.probNumber} mb-2`}>
                    {data.ml_analysis.risk_score_pct.toFixed(2)}%
                  </div>
                  <p className={`text-sm font-medium ${riskTheme.probLabel}`}>
                    Risk Confidence Index
                  </p>
                </div>

                {/* CLAIM OUTCOME / PAYMENT (dataset history or open SF case) */}
                {data.claim_record && (
                  <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-200">
                    <h3 className="text-xs font-black uppercase tracking-widest text-slate-500 mb-3">
                      Claim Status
                    </h3>
                    <div className="space-y-2 text-sm">
                      {data.claim_record.claim_status && !data.claim_record.target_outcome ? (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-500 text-xs">Case status</span>
                          <span className="text-[10px] font-black uppercase px-2.5 py-1 rounded-full bg-sky-100 text-sky-800 border border-sky-200">
                            {data.claim_record.claim_status}
                          </span>
                        </div>
                      ) : data.claim_record.target_outcome ? (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-500 text-xs">Historical outcome</span>
                          <span
                            className={`text-[10px] font-black uppercase px-2.5 py-1 rounded-full ${
                              data.claim_record.target_outcome === "Escalated"
                                ? "bg-red-100 text-red-800 border border-red-200"
                                : "bg-emerald-100 text-emerald-800 border border-emerald-200"
                            }`}
                          >
                            {data.claim_record.target_outcome}
                          </span>
                        </div>
                      ) : (
                        <div className="text-xs text-slate-500 italic">
                          Open case — final outcome not in dataset (e.g. Salesforce)
                        </div>
                      )}
                      {data.claim_record.action_status && (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-500 text-xs">Adjuster action</span>
                          <span
                            className={`text-[10px] font-black uppercase px-2.5 py-1 rounded-full ${
                              data.claim_record.action_status === "No action taken"
                                ? "bg-amber-100 text-amber-800 border border-amber-200"
                                : "bg-slate-100 text-slate-700 border border-slate-200"
                            }`}
                          >
                            {data.claim_record.action_status}
                          </span>
                        </div>
                      )}
                      {data.claim_record.payment_status && (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-500 text-xs">Payment status</span>
                          <span className="text-xs font-bold text-slate-800">
                            {data.claim_record.payment_status}
                          </span>
                        </div>
                      )}
                      {data.claim_record.approved_amount != null &&
                        data.claim_record.approved_amount > 0 && (
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-slate-500 text-xs">Approved amount</span>
                            <span className="text-xs font-bold text-slate-800">
                              ${data.claim_record.approved_amount.toLocaleString(undefined, {
                                maximumFractionDigits: 0,
                              })}
                            </span>
                          </div>
                        )}
                      {data.claim_record.target_outcome === "Escalated" &&
                        data.claim_record.days_open != null && (
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-slate-500 text-xs">Days open at escalation</span>
                            <span className="text-xs font-bold text-slate-800">
                              {data.claim_record.days_open} days
                            </span>
                          </div>
                        )}
                      {data.claim_record.total_claimed != null && (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-500 text-xs">Total claimed</span>
                          <span className="text-xs font-bold text-slate-800">
                            ${data.claim_record.total_claimed.toLocaleString(undefined, {
                              maximumFractionDigits: 0,
                            })}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* ADJUSTER FEEDBACK */}
                <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-200">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-black uppercase tracking-widest text-slate-500">
                      👩‍💼 Adjuster Verdict
                    </h3>
                    {feedbackState.last && feedbackState.locked && !feedbackState.stale && (
                      <span className="text-[9px] font-black uppercase px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200">
                        ✓ Saved
                      </span>
                    )}
                    {feedbackState.stale && (
                      <span className="text-[9px] font-black uppercase px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200">
                        Score changed
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <button
                      onClick={() => submitFeedback("agree")}
                      disabled={
                        feedbackState.submitting ||
                        (feedbackState.locked && !feedbackState.stale)
                      }
                      className={`text-[10px] font-black uppercase py-2 rounded-lg border transition-all ${
                        feedbackState.last === "agree"
                          ? "bg-emerald-600 text-white border-emerald-600"
                          : "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100"
                      } ${feedbackState.locked && !feedbackState.stale ? "opacity-90 cursor-default" : ""}`}
                    >
                      ✓ Agree
                    </button>
                    <button
                      onClick={() => submitFeedback("disagree_too_high")}
                      disabled={
                        feedbackState.submitting ||
                        (feedbackState.locked && !feedbackState.stale)
                      }
                      className={`text-[10px] font-black uppercase py-2 rounded-lg border transition-all ${
                        feedbackState.last === "disagree_too_high"
                          ? "bg-amber-600 text-white border-amber-600"
                          : "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100"
                      } ${feedbackState.locked && !feedbackState.stale ? "opacity-90 cursor-default" : ""}`}
                    >
                      ↓ Too high
                    </button>
                    <button
                      onClick={() => submitFeedback("disagree_too_low")}
                      disabled={
                        feedbackState.submitting ||
                        (feedbackState.locked && !feedbackState.stale)
                      }
                      className={`text-[10px] font-black uppercase py-2 rounded-lg border transition-all ${
                        feedbackState.last === "disagree_too_low"
                          ? "bg-red-600 text-white border-red-600"
                          : "bg-red-50 text-red-700 border-red-200 hover:bg-red-100"
                      } ${feedbackState.locked && !feedbackState.stale ? "opacity-90 cursor-default" : ""}`}
                    >
                      ↑ Too low
                    </button>
                  </div>
                  {feedbackState.message && (
                    <p
                      className={`text-[10px] mt-3 italic ${
                        feedbackState.stale ? "text-amber-700" : "text-slate-500"
                      }`}
                    >
                      {feedbackState.message}
                    </p>
                  )}
                </div>

                {/* TIME-TO-ESCALATION */}
                {data.timeline && (
                  <div className="bg-white p-6 rounded-3xl shadow-sm border border-slate-200">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-xs font-black uppercase tracking-widest text-slate-500">
                        ⏱ Time-to-Escalation
                      </h3>
                      <span className="text-[9px] font-black uppercase px-2.5 py-1 rounded-full border bg-sky-100 text-sky-700 border-sky-200">
                        MAE ±{data.timeline.mae_days.toFixed(0)}d
                      </span>
                    </div>
                    {(() => {
                      const t = data.timeline!;
                      const remaining = t.days_remaining;
                      const color =
                        remaining === null
                          ? "text-slate-700"
                          : remaining <= 0
                          ? "text-red-600"
                          : remaining < 14
                          ? "text-red-600"
                          : remaining < 45
                          ? "text-amber-600"
                          : "text-emerald-700";
                      const bigNum =
                        remaining === null
                          ? `Day ${Math.round(t.predicted_escalation_day)}`
                          : remaining <= 0
                          ? "Overdue"
                          : `~${Math.round(remaining)}d`;
                      return (
                        <>
                          <div className={`text-4xl font-black ${color} mb-1`}>{bigNum}</div>
                          <div className="text-xs text-slate-600 leading-snug">{t.label}</div>
                          <div className="mt-3 grid grid-cols-2 gap-2 text-center">
                            <div className="p-2 bg-slate-50 rounded-lg">
                              <div className="text-[9px] text-slate-400 font-bold uppercase">
                                Today
                              </div>
                              <div className="text-xs font-black text-slate-700">
                                {t.current_days_open !== null
                                  ? `Day ${Math.round(t.current_days_open)}`
                                  : "—"}
                              </div>
                            </div>
                            <div className="p-2 bg-sky-50 rounded-lg">
                              <div className="text-[9px] text-sky-600 font-bold uppercase">
                                Predicted
                              </div>
                              <div className="text-xs font-black text-sky-700">
                                Day {Math.round(t.predicted_escalation_day)}
                              </div>
                            </div>
                          </div>
                          {t.n_training_claims && (
                            <p className="text-[10px] text-slate-400 mt-3 italic">
                              Trained on {t.n_training_claims} prior escalations
                            </p>
                          )}
                        </>
                      );
                    })()}
                  </div>
                )}

                {/* MODEL CONSENSUS */}
                {consensus && consensusBadge && (
                  <div className="bg-white p-6 rounded-3xl shadow-sm border border-slate-200">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-xs font-black uppercase tracking-widest text-slate-500">
                        🧠 Model Consensus
                      </h3>
                      <span
                        className={`text-[9px] font-black uppercase px-2.5 py-1 rounded-full border ${consensusBadge.bg}`}
                      >
                        {consensusBadge.icon} {consensusBadge.label}
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed mb-4">
                      {consensus.message}
                    </p>
                    <div className="grid grid-cols-3 gap-2 text-center">
                      <div className="p-2 bg-slate-50 rounded-lg">
                        <div className="text-[9px] text-slate-400 font-bold uppercase">ML Model</div>
                        <div className={`text-xs font-black mt-0.5 ${signalStyle(consensus.signals.ml_model)}`}>
                          {signalDisplay(consensus.signals.ml_model)}
                        </div>
                      </div>
                      <div className="p-2 bg-green-50 rounded-lg">
                        <div className="text-[9px] text-green-600 font-bold uppercase">Groq</div>
                        <div className={`text-xs font-black mt-0.5 ${signalStyle(consensus.signals.groq)}`}>
                          {signalDisplay(consensus.signals.groq)}
                        </div>
                      </div>
                      <div className="p-2 bg-blue-50 rounded-lg">
                        <div className="text-[9px] text-blue-600 font-bold uppercase">Gemini</div>
                        <div className={`text-xs font-black mt-0.5 ${signalStyle(consensus.signals.gemini)}`}>
                          {signalDisplay(consensus.signals.gemini)}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* RECOMMENDED ACTION */}
                <div className={`${riskTheme.actionBg} p-6 rounded-3xl shadow-xl text-white`}>
                  <div className="flex items-center gap-2 mb-5">
                    <span className="text-lg">🎯</span>
                    <h3
                      className={`text-xs font-black uppercase tracking-widest ${riskTheme.actionAccent}`}
                    >
                      Recommended Action
                    </h3>
                  </div>
                  {strategicActionPoints.length > 0 ? (
                    <ul className="space-y-3">
                      {strategicActionPoints.map((point, i) => (
                        <li
                          key={i}
                          className={`flex items-start gap-3 text-sm ${riskTheme.actionBulletBg} p-3 rounded-xl border ${riskTheme.actionBulletBorder} leading-relaxed`}
                        >
                          <span className={`${riskTheme.actionBullet} font-black shrink-0 mt-0.5`}>
                            {i + 1}.
                          </span>
                          <span>{point}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-white/70 italic">
                      Action plan will appear here once analysis completes (requires GROQ_API_KEY or uses rule-based steps).
                    </p>
                  )}
                  {data.recommended_actions?.source && strategicActionPoints.length > 0 && (
                    <p className="text-[9px] text-white/50 mt-3 uppercase tracking-wider">
                      Source: {data.recommended_actions.source}
                    </p>
                  )}
                </div>

                {/* TRIGGER PHRASES SUMMARY */}
                {data.trigger_analysis && data.trigger_analysis.phrases.length > 0 && (
                  <div className="bg-white p-6 rounded-3xl shadow-sm border border-slate-200">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-xs font-black uppercase tracking-widest text-slate-500">
                        🚨 Trigger Phrases Detected
                      </h3>
                      <span className="text-[9px] font-bold text-slate-400 uppercase">
                        {data.trigger_analysis.source}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {data.trigger_analysis.phrases.map((p, i) => (
                        <span
                          key={i}
                          className={`text-[11px] font-bold px-2 py-1 rounded-lg ${SEVERITY_STYLE[p.severity]}`}
                        >
                          {p.phrase}
                        </span>
                      ))}
                    </div>
                    <p className="text-[10px] text-slate-400 mt-3 italic">
                      Highlighted below in the communication audit
                    </p>
                  </div>
                )}

                {/* DRAFTED NEXT STEP — compact for left column */}
                {availableEmails.length > 0 && (
                  <div className="bg-gradient-to-br from-indigo-600 via-purple-600 to-pink-600 p-[2px] rounded-3xl shadow-xl">
                    <div className="bg-white rounded-[22px] p-6">
                      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
                        <h3 className="text-base font-bold flex items-center gap-2">
                          <span>✍️</span> Drafted Next Step
                        </h3>
                        <button
                          onClick={copyEmail}
                          disabled={!activeEmailDraft?.body}
                          className="bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 rounded-lg text-[10px] font-bold transition-all disabled:opacity-40"
                        >
                          {copied ? "✓ Copied" : "📋 Copy"}
                        </button>
                      </div>

                      <div className="flex p-1 bg-slate-100 rounded-xl mb-4">
                        {availableEmails.map((key) => {
                          const draft = data.next_action_emails?.[key];
                          const hasError = !!draft?.error;
                          const isActive = activeEmail === key;
                          return (
                            <button
                              key={key}
                              onClick={() => setActiveEmail(key)}
                              className={`flex-1 flex items-center justify-center gap-2 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase transition-all ${
                                isActive
                                  ? "bg-white shadow-sm text-slate-800"
                                  : "text-slate-400 hover:text-slate-600"
                              }`}
                            >
                              <span
                                className={`w-1.5 h-1.5 rounded-full ${
                                  hasError
                                    ? "bg-slate-300"
                                    : key === "groq"
                                    ? "bg-green-500"
                                    : "bg-blue-500"
                                }`}
                              ></span>
                              {key === "groq" ? "Llama" : "Gemini"}
                              {hasError && <span>⚠</span>}
                            </button>
                          );
                        })}
                      </div>

                      {activeEmailDraft?.error ? (
                        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl">
                          <div className="text-[10px] font-black uppercase text-amber-700 mb-1 tracking-widest">
                            Draft Unavailable
                          </div>
                          <p className="text-xs text-amber-800">{activeEmailDraft.error}</p>
                        </div>
                      ) : activeEmailDraft?.body ? (
                        <div className="bg-slate-50 rounded-xl p-4 border border-slate-200 max-h-96 overflow-y-auto">
                          {activeEmailDraft.subject && (
                            <div className="pb-2 mb-2 border-b border-slate-200">
                              <div className="text-[9px] font-black uppercase text-slate-400 tracking-widest">
                                Subject
                              </div>
                              <div className="text-xs font-bold text-slate-800 leading-snug mt-0.5">
                                {activeEmailDraft.subject}
                              </div>
                            </div>
                          )}
                          <pre className="text-[11px] text-slate-700 leading-relaxed whitespace-pre-wrap font-sans">
                            {activeEmailDraft.body}
                          </pre>
                        </div>
                      ) : (
                        <p className="text-xs text-slate-400 italic">Draft unavailable.</p>
                      )}

                      <div className="mt-3 flex items-start gap-1.5 text-[10px] text-slate-400 leading-snug">
                        <span>💡</span>
                        <span>
                          Tailored to claim's risk profile and trigger phrases · not legal advice
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* RIGHT COLUMN */}
              <div className="col-span-12 lg:col-span-8 space-y-6">
                {/* AI CONSENSUS */}
                <div className="bg-white p-8 rounded-3xl shadow-sm border border-slate-200">
                  <div className="flex items-center justify-between mb-8 flex-wrap gap-4">
                    <h3 className="text-xl font-bold flex items-center gap-3">
                      <span>🤖</span> AI Strategist Consensus
                    </h3>
                    {availableModels.length > 0 && (
                      <div className="flex p-1 bg-slate-100 rounded-xl">
                        {availableModels.map((key) => {
                          const isActive = activeModel === key;
                          const hasError = looksLikeError(data.ai_consensus[key]);
                          return (
                            <button
                              key={key}
                              onClick={() => setActiveModel(key)}
                              className={`flex items-center gap-2 px-4 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider transition-all ${
                                isActive
                                  ? `bg-white shadow-sm border ${MODEL_META[key].activeClass}`
                                  : "text-slate-400 hover:text-slate-600 border border-transparent"
                              }`}
                            >
                              <span
                                className={`w-1.5 h-1.5 rounded-full ${
                                  hasError ? "bg-slate-300" : MODEL_META[key].dotClass
                                }`}
                              ></span>
                              {MODEL_META[key].label}
                              {hasError && <span className="text-slate-400">⚠</span>}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <div>
                    {activeModelText ? (
                      activeModelHasError ? (
                        <div className="p-5 bg-amber-50 border border-amber-200 rounded-2xl">
                          <div className="text-[10px] font-black uppercase text-amber-700 mb-2 tracking-widest">
                            Model Error
                          </div>
                          <p className="text-sm text-amber-800 leading-relaxed">
                            {activeModelText}
                          </p>
                        </div>
                      ) : (
                        <>
                          {activeModelTruncated && (
                            <div className="p-4 mb-4 bg-amber-50 border border-amber-200 rounded-2xl text-sm text-amber-900">
                              <span className="font-bold">Incomplete brief.</span> Click{" "}
                              <strong>Run Analysis</strong> again after restarting the API
                              (Gemini 2.5 thinking budget fix). Cached results may be stale.
                            </div>
                          )}
                          <div className="prose prose-slate prose-sm max-w-none text-slate-600 leading-relaxed">
                            <ReactMarkdown>{activeModelText}</ReactMarkdown>
                          </div>
                        </>
                      )
                    ) : (
                      <p className="text-slate-400 text-sm italic">
                        No AI analysis available for this claim.
                      </p>
                    )}
                  </div>

                  {usSpotlight && (
                    <div className="mt-8 pt-8 border-t border-slate-200">
                      <div className="flex items-center gap-2 mb-4">
                        <span className="text-lg">⚖️</span>
                        <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">
                          Key US Legal Precedent
                        </h4>
                      </div>
                      <a
                        href={usSpotlight.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-lg font-extrabold text-blue-700 hover:underline leading-tight block mb-3"
                      >
                        {usSpotlight.title} ↗
                      </a>
                      {data.legal_context.us_spotlight_relevance && (
                        <div className="mb-3 p-3 bg-blue-50 border border-blue-100 rounded-xl">
                          <div className="text-[9px] font-black uppercase text-blue-600 tracking-widest mb-1">
                            Relevance to this claim
                          </div>
                          <p className="text-xs text-blue-900 leading-relaxed">
                            {data.legal_context.us_spotlight_relevance}
                          </p>
                        </div>
                      )}
                      {data.legal_context.us_spotlight_description ? (
                        <p className="text-sm text-slate-600 leading-relaxed">
                          {data.legal_context.us_spotlight_description}
                        </p>
                      ) : (
                        <p className="text-xs text-slate-400 italic">
                          AI case summary unavailable.
                        </p>
                      )}
                    </div>
                  )}
                </div>

                {/* LEGAL LIBRARY */}
                <div className="bg-white p-8 rounded-3xl shadow-sm border border-slate-200">
                  <div className="flex justify-between items-center mb-4 flex-wrap gap-3">
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">
                      Global Legal Library
                    </h3>
                    <div className="flex p-1 bg-slate-100 rounded-xl">
                      <button
                        onClick={() => setActiveRegion("US")}
                        className={`px-4 py-1.5 rounded-lg text-[10px] font-black uppercase transition-all ${
                          activeRegion === "US"
                            ? "bg-white text-blue-600 shadow-sm"
                            : "text-slate-400"
                        }`}
                      >
                        US (
                        {
                          data.legal_context.precedents.filter(
                            (p) => p.jurisdiction?.toUpperCase() === "US"
                          ).length
                        }
                        )
                      </button>
                      <button
                        onClick={() => setActiveRegion("India")}
                        className={`px-4 py-1.5 rounded-lg text-[10px] font-black uppercase transition-all ${
                          activeRegion === "India"
                            ? "bg-white text-blue-600 shadow-sm"
                            : "text-slate-400"
                        }`}
                      >
                        India (
                        {
                          data.legal_context.precedents.filter(
                            (p) => p.jurisdiction?.toLowerCase() === "india"
                          ).length
                        }
                        )
                      </button>
                    </div>
                  </div>

                  {activeRegion === "US" && data.legal_context.matched_query && (
                    <div className="mb-6 p-3 bg-indigo-50 border border-indigo-200 rounded-xl flex items-center gap-2">
                      <span className="text-indigo-600">🎯</span>
                      <div className="flex-1">
                        <div className="text-[9px] font-black uppercase text-indigo-600 tracking-widest">
                          Fact-Matched Search
                        </div>
                        <div className="text-xs text-indigo-900 font-mono">
                          "{data.legal_context.matched_query}"
                        </div>
                      </div>
                      <span className="text-[9px] text-indigo-500 font-bold">
                        Tailored to this claim
                      </span>
                    </div>
                  )}

                  <div className="grid gap-4">
                    {filteredPrecedents.length > 0 ? (
                      filteredPrecedents.map((caseItem, idx) => (
                        <a
                          key={idx}
                          href={caseItem.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="group flex justify-between items-center p-4 rounded-2xl bg-slate-50 hover:bg-white hover:shadow-md transition-all border border-transparent hover:border-slate-200"
                        >
                          <div className="flex-1 pr-4">
                            <h4 className="text-blue-600 font-bold text-sm group-hover:underline">
                              {caseItem.title}
                            </h4>
                            <p className="text-[10px] text-slate-500 mt-1 line-clamp-1 italic">
                              {caseItem.headline}
                            </p>
                          </div>
                          <span className="text-slate-300 group-hover:text-blue-500">↗</span>
                        </a>
                      ))
                    ) : (
                      <div className="text-center py-10 border-2 border-dashed border-slate-100 rounded-2xl">
                        <p className="text-slate-400 text-sm italic">{emptyStateMessage()}</p>
                      </div>
                    )}
                  </div>
                </div>

                {/* SIMILAR HISTORICAL CLAIMS */}
                {data.similar_claims && data.similar_claims.neighbours.length > 0 && (
                  <div className="bg-white p-8 rounded-3xl shadow-sm border border-slate-200">
                    <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
                      <div>
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">
                          🧭 Similar Past Claims · Nearest Neighbours
                        </h3>
                        <p className="text-[11px] text-slate-500 mt-1">
                          Semantic match over the text of all 550 historical claims.
                        </p>
                      </div>
                      {(() => {
                        const rate = data.similar_claims!.escalation_rate_in_neighbourhood;
                        const badgeCls =
                          rate >= 0.6
                            ? "bg-red-100 text-red-700 border-red-200"
                            : rate >= 0.3
                            ? "bg-amber-100 text-amber-800 border-amber-200"
                            : "bg-emerald-100 text-emerald-700 border-emerald-200";
                        return (
                          <span
                            className={`text-[10px] font-black uppercase px-3 py-1.5 rounded-full border ${badgeCls}`}
                          >
                            {data.similar_claims!.escalated_in_top_k}/
                            {data.similar_claims!.top_k} escalated
                          </span>
                        );
                      })()}
                    </div>
                    <div className="grid gap-2">
                      {data.similar_claims.neighbours.map((n) => {
                        const escalated = n.outcome === "Escalated";
                        return (
                          <a
                            key={n.claim_id}
                            href={`/claim?id=${encodeURIComponent(n.claim_id)}`}
                            className={`flex items-center gap-4 p-4 rounded-2xl border transition-all hover:shadow-md ${
                              escalated
                                ? "bg-red-50/50 border-red-100 hover:bg-red-50"
                                : "bg-emerald-50/50 border-emerald-100 hover:bg-emerald-50"
                            }`}
                          >
                            <div className="w-16 text-center shrink-0">
                              <div
                                className={`text-xl font-black ${
                                  escalated ? "text-red-700" : "text-emerald-700"
                                }`}
                              >
                                {(n.similarity * 100).toFixed(0)}%
                              </div>
                              <div className="text-[9px] font-bold text-slate-400 uppercase">
                                similarity
                              </div>
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-mono text-[11px] font-bold text-slate-700">
                                  {n.claim_id}
                                </span>
                                <span
                                  className={`text-[9px] font-black uppercase px-2 py-0.5 rounded-full ${
                                    escalated
                                      ? "bg-red-200 text-red-800"
                                      : "bg-emerald-200 text-emerald-800"
                                  }`}
                                >
                                  {n.outcome}
                                </span>
                              </div>
                              <div className="text-[11px] text-slate-600 truncate">
                                {n.incident_type} · {n.policy_type}
                              </div>
                              <div className="text-[10px] text-slate-400 mt-0.5">
                                {n.days_open !== null && `${n.days_open} days open · `}
                                {n.total_claimed !== null &&
                                  `claimed $${n.total_claimed.toLocaleString(undefined, {
                                    maximumFractionDigits: 0,
                                  })}`}
                                {n.approved_amount !== null &&
                                  ` · approved $${n.approved_amount.toLocaleString(undefined, {
                                    maximumFractionDigits: 0,
                                  })}`}
                              </div>
                            </div>
                            <span className="text-slate-300">→</span>
                          </a>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* DEMO_HIDE: Audit Trail — the defensibility panel. Flip DEMO_HIDE_OPS_PANELS (top of file) to false to restore. */}
            {!DEMO_HIDE_OPS_PANELS && (
            <div className="bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-8 rounded-3xl shadow-xl text-white">
              <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">📜</span>
                  <div>
                    <h3 className="text-xl font-bold">Audit Trail</h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Every number on this page has a source. This panel proves the score is defensible.
                    </p>
                  </div>
                </div>
                <span className="text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-full border bg-slate-800 text-slate-300 border-slate-700">
                  Regulator-ready
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
                {/* Score breakdown */}
                {data.ml_analysis.calibration && (
                  <div className="bg-slate-800/50 rounded-2xl p-5 border border-slate-700">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-3">
                      Score Construction
                    </div>
                    <div className="space-y-2 text-xs">
                      <AuditRow
                        label="Raw ensemble (40/60)"
                        value={`${data.ml_analysis.calibration.raw_ml_score.toFixed(1)}%`}
                      />
                      <AuditRow
                        label={`Calibrated (${data.ml_analysis.calibration.method})`}
                        value={`${data.ml_analysis.calibration.structured_calibrated.toFixed(1)}%`}
                      />
                      <AuditRow
                        label="Unstructured signal"
                        value={`${data.ml_analysis.calibration.unstructured_score.toFixed(1)}%`}
                      />
                      <AuditRow
                        label={`Weighted blend ${data.ml_analysis.calibration.weights.structured} / ${data.ml_analysis.calibration.weights.unstructured}`}
                        value={`${data.ml_analysis.calibration.final.toFixed(1)}%`}
                        highlight
                      />
                    </div>
                  </div>
                )}

                {/* SHAP warning signs */}
                <div className="bg-slate-800/50 rounded-2xl p-5 border border-slate-700">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-3">
                    SHAP — Top Risk Drivers
                  </div>
                  {data.ml_analysis.top_warning_signs.length > 0 ? (
                    <ul className="space-y-1.5 text-xs">
                      {data.ml_analysis.top_warning_signs.map((sign, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <span className="text-red-400 font-black shrink-0">{i + 1}.</span>
                          <span className="text-slate-200">{sign}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500 italic">No positive SHAP contributors.</p>
                  )}
                  {data.ml_analysis.model_a_contribution !== undefined && (
                    <div className="mt-3 pt-3 border-t border-slate-700 text-[10px] text-slate-400">
                      Model A (structured): {data.ml_analysis.model_a_contribution.toFixed(1)}% · Model B
                      (NLP): {data.ml_analysis.model_b_contribution?.toFixed(1)}%
                    </div>
                  )}
                </div>

                {/* Citations + grounding status */}
                <div className="bg-slate-800/50 rounded-2xl p-5 border border-slate-700">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-3">
                    LLM Citation Grounding
                  </div>
                  {(["groq_llama", "google_gemini"] as const).map((k) => {
                    const g = data.ai_consensus[`${k}_grounding` as keyof typeof data.ai_consensus] as
                      | Grounding
                      | null
                      | undefined;
                    if (!g) {
                      return (
                        <div key={k} className="text-[11px] text-slate-500 italic mb-2">
                          {k === "groq_llama" ? "Llama" : "Gemini"}: not used
                        </div>
                      );
                    }
                    const unsupported = g.unsupported_citations.length;
                    const ok = unsupported === 0;
                    return (
                      <div
                        key={k}
                        className={`mb-2 p-2 rounded-lg border ${
                          ok
                            ? "bg-emerald-900/30 border-emerald-700/50"
                            : "bg-amber-900/30 border-amber-700/50"
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[11px] font-bold">
                            {k === "groq_llama" ? "Llama 3.1" : "Gemini 2.5"}
                          </span>
                          <span
                            className={`text-[9px] font-black uppercase px-2 py-0.5 rounded-full ${
                              ok
                                ? "bg-emerald-500/20 text-emerald-300"
                                : "bg-amber-500/20 text-amber-300"
                            }`}
                          >
                            {ok ? "✓ Grounded" : `⚠ ${unsupported} unsupported`}
                          </span>
                        </div>
                        <div className="text-[10px] text-slate-400">
                          {g.citations_found.length} cited · {g.allowed_cases.length} allowed · T={g.temperature}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Trigger phrases row */}
              {data.trigger_analysis && data.trigger_analysis.phrases.length > 0 && (
                <div className="bg-slate-800/50 rounded-2xl p-5 border border-slate-700">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">
                      Trigger Phrases Detected in Text
                    </div>
                    <span className="text-[10px] text-slate-500">
                      Source: {data.trigger_analysis.source} · weight {data.trigger_analysis.risk_weight}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {data.trigger_analysis.phrases.map((p, i) => (
                      <span
                        key={i}
                        className={`text-[11px] font-bold px-2 py-1 rounded-lg ${SEVERITY_STYLE[p.severity]}`}
                      >
                        {p.phrase}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
            )}

            {/* COMMUNICATION AUDIT */}
            <div className={`p-8 rounded-3xl shadow-sm border-2 ${riskTheme.audAccent}`}>
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <span className={`w-3 h-3 rounded-full ${riskTheme.audDot} animate-pulse`}></span>
                  <h3 className="text-xl font-bold flex items-center gap-3">
                    <span>📡</span> Communication Audit
                  </h3>
                </div>
                <div className="flex items-center gap-3">
                  {data.trigger_analysis && data.trigger_analysis.phrases.length > 0 && (
                    <span className="text-[10px] font-black uppercase px-3 py-1 rounded-full border bg-red-100 text-red-700 border-red-200">
                      {data.trigger_analysis.phrases.length} TRIGGERS
                    </span>
                  )}
                  <span
                    className={`text-[10px] font-black uppercase px-3 py-1 rounded-full border ${riskTheme.audBadgeBg}`}
                  >
                    {riskTheme.audLabel}
                  </span>
                </div>
              </div>

              {hasAnyAudit ? (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {audit!.incident_description && (
                    <div
                      className={`bg-white p-6 rounded-2xl border ${riskTheme.audCardBorder} shadow-sm`}
                    >
                      <div className="flex items-center gap-2 mb-3">
                        <span>📝</span>
                        <h4
                          className={`text-[10px] font-black uppercase tracking-widest ${riskTheme.audCardTitle}`}
                        >
                          Incident Description
                        </h4>
                      </div>
                      <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
                        {audit!.incident_description}
                      </p>
                    </div>
                  )}
                  {audit!.adjuster_notes && (
                    <div
                      className={`bg-white p-6 rounded-2xl border ${riskTheme.audCardBorder} shadow-sm`}
                    >
                      <div className="flex items-center gap-2 mb-3">
                        <span>📞</span>
                        <h4
                          className={`text-[10px] font-black uppercase tracking-widest ${riskTheme.audCardTitle}`}
                        >
                          Adjuster Contact Log
                        </h4>
                      </div>
                      <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
                        {renderHighlighted(
                          audit!.adjuster_notes,
                          data.trigger_analysis?.adjuster_matches || []
                        )}
                      </p>
                    </div>
                  )}
                  {audit!.email_transcript && (
                    <div
                      className={`bg-white p-6 rounded-2xl border ${riskTheme.audCardBorder} shadow-sm`}
                    >
                      <div className="flex items-center gap-2 mb-3">
                        <span>✉️</span>
                        <h4
                          className={`text-[10px] font-black uppercase tracking-widest ${riskTheme.audCardTitle}`}
                        >
                          Claimant Email
                        </h4>
                      </div>
                      <pre className="text-[11px] text-slate-600 leading-relaxed whitespace-pre-wrap font-mono bg-slate-50 p-3 rounded-lg max-h-80 overflow-y-auto">
                        {renderHighlighted(
                          audit!.email_transcript,
                          data.trigger_analysis?.email_matches || []
                        )}
                      </pre>
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-12 text-center border-2 border-dashed border-slate-200 rounded-2xl bg-white/50">
                  <div className="text-3xl mb-2 opacity-50">📭</div>
                  <p className="text-slate-500 text-sm font-medium mb-1">
                    No communication records for this claim
                  </p>
                  <p className="text-slate-400 text-xs italic">
                    Incident descriptions, adjuster notes, and emails are not available for{" "}
                    <span className="font-mono">{data.claim_id}</span>.
                  </p>
                </div>
              )}
            </div>
          </div>
        ) : (
          !loading && (
            <div className="flex flex-col items-center justify-center py-32 opacity-40">
              <div className="text-6xl mb-4">🔍</div>
              <div className="text-slate-500 font-medium italic">
                Enter a Claim ID or open the queue to start.
              </div>
            </div>
          )
        )}
      </div>
    </>
  );
}

export default function ClaimPage() {
  return (
    <Suspense
      fallback={
        <div className="max-w-7xl mx-auto py-32 text-center text-slate-400 italic">
          Loading claim...
        </div>
      }
    >
      <RiskDashboard />
    </Suspense>
  );
}

function AuditRow({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 ${
        highlight ? "pt-2 border-t border-slate-700" : ""
      }`}
    >
      <span className="text-slate-400">{label}</span>
      <span className={`font-mono font-black ${highlight ? "text-white text-sm" : "text-slate-200"}`}>
        {value}
      </span>
    </div>
  );
}