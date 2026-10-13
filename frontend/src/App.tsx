import { useEffect, useRef, useState } from "react";
import CorpusScreen from "./CorpusScreen";
import { SavedDashboard, SavedAssessmentView } from "./SavedAssessments";
import {
  changePassword, checkClaim, forgotPassword, getClaim, getClaims, getMe, getSource, login, logout,
  onUnauthorized, registerCsvUrl, resetPassword, signup, updateProfile, useApi,
  type Assessment, type CheckResponse, type Evidence, type LineageLink, type Mode, type SourceAttestation, type Stance, type User,
} from "./api";
import OrganisationScreen from "./OrganisationScreen";
import { documents as orgDocuments } from "./orgGraph";

// ─── Screens ──────────────────────────────────────────────────────────────────

type Screen =
  | "login"
  | "signup"
  | "forgot"
  | "dashboard"
  | "register"
  | "saved-assessment"
  | "check"
  | "assessment"
  | "evidence-detail"
  | "organisation"
  | "sources"
  | "source-detail"
  | "settings"
  | "components";

// ─── Tokens ───────────────────────────────────────────────────────────────────

const ORANGE = "#F26B21";
const GREEN_TEXT = "#1F6B30";
const AMBER_TEXT = "#7A4F0A";
const RED_TEXT = "#991B1B";
const GREY_TEXT = "#6b7280";

const GREEN_BG = "#f0faf2";
const AMBER_BG = "#fef9ed";
const RED_BG = "#fef2f2";
const GREY_BG = "#f5f4f2";

const BORDER = "#e5e3df";
const BORDER_INNER = "#f0eee9";
const SURFACE = "#ffffff";
const PAGE = "#f5f4f2";
const MUTED = "#9ca3af";
const TEXT = "#1a1a1a";
const TEXT2 = "#374151";
const TEXT3 = "#6b7280";

// ─── Icons ────────────────────────────────────────────────────────────────────

function IcoDashboard() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <rect x="1" y="1" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.1" />
      <rect x="8.5" y="1" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.1" />
      <rect x="1" y="8.5" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.1" />
      <rect x="8.5" y="8.5" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  );
}
function IcoClaims() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <rect x="1.5" y="1.5" width="12" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.1" />
      <path d="M4 5h7M4 7.5h7M4 10h4.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}
function IcoOrganisation() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <rect x="5.25" y="1.25" width="4.5" height="3.5" rx="0.8" stroke="currentColor" strokeWidth="1.1" />
      <rect x="1.25" y="10.25" width="4.5" height="3.5" rx="0.8" stroke="currentColor" strokeWidth="1.1" />
      <rect x="9.25" y="10.25" width="4.5" height="3.5" rx="0.8" stroke="currentColor" strokeWidth="1.1" />
      <path d="M7.5 4.75v2.75M3.5 10.25V7.5h8v2.75" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function IcoSources() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <circle cx="4" cy="7.5" r="2.5" stroke="currentColor" strokeWidth="1.1" />
      <circle cx="11" cy="3" r="2" stroke="currentColor" strokeWidth="1.1" />
      <circle cx="11" cy="12" r="2" stroke="currentColor" strokeWidth="1.1" />
      <path d="M6.4 6.5l2.7-2M6.4 8.5l2.7 2" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}
function IcoSettings() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <circle cx="7.5" cy="7.5" r="2" stroke="currentColor" strokeWidth="1.1" />
      <path d="M7.5 1v1.5M7.5 12.5V14M14 7.5h-1.5M2.5 7.5H1M12.07 2.93l-1.06 1.06M4 11l-1.07 1.07M12.07 12.07l-1.06-1.06M4 4 2.93 2.93" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}
function IcoSearch() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="6" cy="6" r="4.5" stroke={MUTED} strokeWidth="1.2" />
      <path d="M9.5 9.5l2.5 2.5" stroke={MUTED} strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}
function IcoChevron() {
  return (
    <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
      <path d="M2.5 4l3 3 3-3" stroke={MUTED} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function IcoPlus({ color = GREEN_TEXT }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="6.5" stroke={color} />
      <path d="M7 4v6M4 7h6" stroke={color} strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}
function IcoMinus({ color = RED_TEXT }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="6.5" stroke={color} />
      <path d="M4 7h6" stroke={color} strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}
function IcoMerge() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="6.5" stroke={GREY_TEXT} />
      <path d="M5 4.5v3l2 2 2-2V4.5" stroke={GREY_TEXT} strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7 9.5v1" stroke={GREY_TEXT} strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}

// ─── Data helpers ─────────────────────────────────────────────────────────────

// What the assessment screen is showing: a register Fact, or a free-text claim to retrieve.
type ClaimTarget = { kind: "fact"; factId: string } | { kind: "query"; text: string; asOf: string; run: number };

type Nav = {
  go: (s: Screen) => void;
  openClaim: (factId: string) => void;
  openSaved: (runId: string) => void;
  checkClaim: (text: string, asOf?: string) => void;
  openEvidence: (evidence: Evidence) => void;
  openSource: (documentId: string) => void;
};

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
}

const words = (value: string | null | undefined) => (value ? value.replace(/_/g, " ") : "—");

function outcomeColor(outcome: string) {
  if (outcome === "Supported") return GREEN_TEXT;
  if (outcome === "Contested") return AMBER_TEXT;
  if (outcome === "Contradicted") return RED_TEXT;
  return MUTED;
}

function statusVariant(status: string): PillVariant {
  if (status === "current" || status === "approved") return "green";
  if (status === "draft" || status === "unapproved") return "amber";
  return "grey";
}

const CONFIDENCE: Record<string, { label: string; pct: number }> = {
  "Higher confidence": { label: "High", pct: 88 },
  "Moderate confidence": { label: "Medium", pct: 55 },
  "Lower confidence": { label: "Low", pct: 18 },
};

const STANCE_WORD: Record<Stance, string> = { support: "Supports", contradict: "Contradicts", qualify: "Qualifies" };

function downloadJson(filename: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

// ─── Shared: loading / error state ────────────────────────────────────────────

function LoadState({ error }: { error: string | null }) {
  return (
    <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "40px 24px", textAlign: "center", fontSize: 13.5, color: MUTED }}>
      {error ? (
        <>
          <div style={{ color: TEXT2, fontWeight: 500, marginBottom: 4 }}>Could not load this from the API.</div>
          <div>{error}</div>
        </>
      ) : (
        "Loading…"
      )}
    </div>
  );
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

function Sidebar({ screen, setScreen }: { screen: Screen; setScreen: (s: Screen) => void }) {
  const items: { label: string; icon: React.ReactNode; target: Screen }[] = [
    { label: "Dashboard", icon: <IcoDashboard />, target: "dashboard" },
    { label: "Claims",    icon: <IcoClaims />,    target: "assessment" },
    { label: "Organisation", icon: <IcoOrganisation />, target: "organisation" },
    { label: "Sources",   icon: <IcoSources />,   target: "sources" },
    { label: "Settings",  icon: <IcoSettings />,  target: "settings" },
  ];

  const isActive = (target: Screen) => {
    if (target === "dashboard") return ["dashboard", "register", "saved-assessment"].includes(screen);
    if (target === "assessment") return screen === "assessment" || screen === "check" || screen === "evidence-detail";
    if (target === "organisation") return screen === "organisation";
    if (target === "sources") return screen === "sources" || screen === "source-detail" || screen === "components";
    if (target === "settings") return screen === "settings";
    return false;
  };

  return (
    <aside style={{ width: 240, flexShrink: 0, background: SURFACE, borderRight: `1px solid ${BORDER}`, display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: "28px 24px 24px", borderBottom: `1px solid ${BORDER}` }}>
        <div style={{ fontWeight: 600, fontSize: 15, letterSpacing: "-0.01em", color: TEXT }}>Claim checker</div>
      </div>

      <nav style={{ padding: "12px 12px", flex: 1 }}>
        {items.map(({ label, icon, target }) => {
          const active = isActive(target);
          return (
            <button
              key={label}
              onClick={() => setScreen(target)}
              style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%",
                padding: "9px 12px", borderRadius: 6, border: "none",
                cursor: target ? "pointer" : "default",
                background: active ? `${ORANGE}12` : "transparent",
                color: active ? ORANGE : TEXT3,
                fontSize: 13.5, fontWeight: active ? 500 : 400,
                fontFamily: "Inter, sans-serif", textAlign: "left", marginBottom: 2,
              }}
            >
              <span style={{ opacity: active ? 1 : 0.65 }}>{icon}</span>
              {label}
            </button>
          );
        })}
      </nav>

      <div style={{ padding: "20px 16px", borderTop: `1px solid ${BORDER}` }}>
        <button
          onClick={() => setScreen("check")}
          style={{
            display: "block", width: "100%", padding: "10px 16px",
            background: ORANGE, color: "#fff", border: "none", borderRadius: 6,
            fontSize: 13.5, fontWeight: 500, fontFamily: "Inter, sans-serif",
            cursor: "pointer", textAlign: "center",
          }}
        >
          Check a claim
        </button>
      </div>
    </aside>
  );
}

// ─── Top bar ──────────────────────────────────────────────────────────────────

function initials(name: string) {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

function TopBar({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the account menu on an outside click or Escape.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div style={{ height: 48, background: SURFACE, borderBottom: `1px solid ${BORDER}`, display: "flex", alignItems: "center", justifyContent: "flex-end", padding: "0 32px", flexShrink: 0 }}>
      <div ref={menuRef} style={{ position: "relative" }}>
        <button
          onClick={() => setOpen(!open)}
          aria-haspopup="menu" aria-expanded={open} aria-label="Account menu"
          style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 6px 4px 10px", background: open ? GREY_BG : "transparent", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "Inter, sans-serif" }}
        >
          <span style={{ fontSize: 12, color: MUTED }}>{user.name}</span>
          <span style={{ width: 26, height: 26, borderRadius: "50%", background: ORANGE, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 600, color: "#fff" }}>{initials(user.name)}</span>
        </button>

        {open && (
          <div role="menu" style={{ position: "absolute", top: "calc(100% + 6px)", right: 0, minWidth: 220, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden", zIndex: 20 }}>
            <div style={{ padding: "12px 14px", borderBottom: `1px solid ${BORDER_INNER}` }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: TEXT }}>{user.name}</div>
              <div style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>{user.email}</div>
            </div>
            <button
              role="menuitem"
              onClick={() => { setOpen(false); onSignOut(); }}
              style={{ display: "block", width: "100%", padding: "10px 14px", background: "transparent", border: "none", textAlign: "left", fontSize: 13, color: TEXT2, cursor: "pointer", fontFamily: "Inter, sans-serif" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#faf9f7")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Shared: verdict badge ────────────────────────────────────────────────────

type VerdictLabel = "supported" | "contested" | "insufficient evidence" | "contradicted" | "no authority";

function VerdictBadge({ verdict }: { verdict: VerdictLabel }) {
  const map: Record<string, { color: string; bg: string; border: string }> = {
    "supported":            { color: GREEN_TEXT,  bg: GREEN_BG,  border: `${GREEN_TEXT}25` },
    "contested":            { color: AMBER_TEXT,  bg: AMBER_BG,  border: `${AMBER_TEXT}25` },
    "contradicted":         { color: RED_TEXT,    bg: RED_BG,    border: `${RED_TEXT}25`   },
    "insufficient evidence":{ color: GREY_TEXT,   bg: GREY_BG,   border: BORDER            },
    "no authority":         { color: "#92400e",   bg: "#fff7ed", border: "#f59e0b40"        },
  };
  const s = map[verdict] ?? { color: GREY_TEXT, bg: GREY_BG, border: BORDER };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", fontSize: 11.5, fontWeight: 500, padding: "3px 8px", borderRadius: 4, whiteSpace: "nowrap", color: s.color, background: s.bg, border: `1px solid ${s.border}` }}>
      {verdict}
    </span>
  );
}

// ─── Shared: status pill ──────────────────────────────────────────────────────

type PillVariant = "green" | "amber" | "grey";

function StatusPill({ label, variant }: { label: string; variant: PillVariant }) {
  const map: Record<PillVariant, { color: string; bg: string; border: string }> = {
    green: { color: GREEN_TEXT, bg: GREEN_BG, border: `${GREEN_TEXT}25` },
    amber: { color: AMBER_TEXT, bg: AMBER_BG, border: `${AMBER_TEXT}25` },
    grey: { color: GREY_TEXT, bg: GREY_BG, border: BORDER },
  };
  const s = map[variant];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", fontSize: 11, fontWeight: 500, padding: "2px 8px", borderRadius: 4, whiteSpace: "nowrap", color: s.color, background: s.bg, border: `1px solid ${s.border}` }}>
      {label}
    </span>
  );
}

// ─── Shared: confidence bar ───────────────────────────────────────────────────

function ConfidenceBar({ pct, label, note }: { pct: number; label: string; note: string }) {
  return (
    <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "20px 24px", display: "flex", alignItems: "center", gap: 20 }}>
      <div style={{ minWidth: 120 }}>
        <div style={{ fontSize: 11, color: MUTED, marginBottom: 4 }}>Confidence</div>
        <div style={{ fontSize: 14, fontWeight: 500, color: pct > 0 ? TEXT : MUTED }}>{label}</div>
      </div>
      <div style={{ flex: 1, height: 3, background: BORDER_INNER, borderRadius: 2 }}>
        {pct > 0 && <div style={{ width: `${pct}%`, height: "100%", background: "#9ca3af", borderRadius: 2 }} />}
      </div>
      <div style={{ fontSize: 12, color: MUTED, whiteSpace: "nowrap" }}>{note}</div>
    </div>
  );
}

// ─── Shared: claim card ───────────────────────────────────────────────────────

function ClaimCard({ claimText, chips, note, children }: { claimText: string; chips: { key: string; value: string }[]; note?: string; children?: React.ReactNode }) {
  return (
    <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "22px 24px" }}>
      <div style={{ fontSize: 11, color: MUTED, marginBottom: 10 }}>Claim assessed</div>
      <p style={{ fontSize: 16, fontWeight: 500, color: TEXT, lineHeight: 1.5, margin: "0 0 14px", maxWidth: 780 }}>{claimText}</p>
      {note && <p style={{ fontSize: 12.5, color: TEXT3, lineHeight: 1.5, margin: "-6px 0 14px", maxWidth: 780 }}>{note}</p>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {chips.map(({ key, value }) => (
          <span key={key} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, background: GREY_BG, border: `1px solid ${BORDER}`, borderRadius: 4, padding: "3px 9px" }}>
            <span style={{ color: MUTED }}>{key}</span>
            <span style={{ color: "#525252", borderLeft: `1px solid #d4d4d4`, paddingLeft: 5, marginLeft: 1 }}>{value}</span>
          </span>
        ))}
      </div>
      {children}
    </div>
  );
}

// ─── Shared: evidence rows list ───────────────────────────────────────────────

function stanceIcon(stance: Stance) {
  if (stance === "support") return <IcoPlus />;
  if (stance === "contradict") return <IcoMinus />;
  return <IcoMerge />;
}

function evidenceMeta(item: Evidence) {
  if (!item.applicable) return `${item.mode} · out of scope, not scored`;
  return `${item.mode} · materiality ${(item.materiality_score ?? 0).toFixed(2)}`;
}

function evidenceDesc(item: Evidence) {
  const weight = item.applicable && !item.material ? " · weighted down, not discarded" : "";
  return `${STANCE_WORD[item.stance]} · ${item.attests_value}${weight}`;
}

function EvidenceList({ evidence, onRowClick }: { evidence: Evidence[]; onRowClick?: (item: Evidence) => void }) {
  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, color: TEXT, marginBottom: 12 }}>Evidence</div>
      <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden" }}>
        {evidence.map((item, i) => (
          <div
            key={item.edge_id}
            onClick={() => onRowClick?.(item)}
            style={{ display: "grid", gridTemplateColumns: "18px 1fr", alignItems: "start", gap: "0 14px", padding: "14px 20px", borderBottom: i < evidence.length - 1 ? `1px solid ${BORDER_INNER}` : "none", cursor: "pointer" }}
            onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "#faf9f7")}
            onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "transparent")}
          >
            <div style={{ paddingTop: 1 }}>{stanceIcon(item.stance)}</div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
                <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, fontWeight: 500, color: ORANGE, textDecoration: "underline", textUnderlineOffset: 2 }}>{item.document.short_id}</span>
                <StatusPill label={item.lifecycle_status} variant={statusVariant(item.lifecycle_status)} />
                <span style={{ fontSize: 11.5, color: MUTED }}>{evidenceMeta(item)}</span>
              </div>
              <div style={{ fontSize: 12.5, color: TEXT3 }}>{evidenceDesc(item)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Shared: verdict card pair ────────────────────────────────────────────────

type VerdictCardProps = { label: string; value: string; color: string; sub: string };

function VerdictCardPair({ left, right }: { left: VerdictCardProps; right: VerdictCardProps }) {
  return (
    <div style={{ display: "flex", gap: 16 }}>
      {[left, right].map((card) => (
        <div key={card.label} style={{ flex: 1, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "22px 24px" }}>
          <div style={{ fontSize: 11, color: MUTED, marginBottom: 10 }}>{card.label}</div>
          <div style={{ fontSize: 17, fontWeight: 600, color: card.color, letterSpacing: "-0.01em", marginBottom: 6 }}>{card.value}</div>
          <div style={{ fontSize: 12.5, color: TEXT3 }}>{card.sub}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Shared: page shell ───────────────────────────────────────────────────────

function PageShell({ children, breadcrumb, actions }: { children: React.ReactNode; breadcrumb?: string; actions?: React.ReactNode }) {
  return (
    <main style={{ flex: 1, overflowY: "auto", padding: "36px 48px" }}>
      {(breadcrumb || actions) && (
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 28 }}>
          <div style={{ fontSize: 12, color: MUTED }}>{breadcrumb}</div>
          {actions && <div style={{ display: "flex", gap: 8 }}>{actions}</div>}
        </div>
      )}
      {children}
    </main>
  );
}

// ─── Btn ──────────────────────────────────────────────────────────────────────

function Btn({ children, variant = "primary", onClick, disabled, title }: { children: React.ReactNode; variant?: "primary" | "secondary" | "link"; onClick?: () => void; disabled?: boolean; title?: string }) {
  const styles = {
    primary: { background: ORANGE, color: "#fff", border: `1px solid ${ORANGE}`, borderRadius: 6, padding: "9px 18px", fontSize: 13.5, fontWeight: 500 },
    secondary: { background: SURFACE, color: TEXT2, border: `1px solid ${BORDER}`, borderRadius: 6, padding: "9px 18px", fontSize: 13.5, fontWeight: 400 },
    link: { background: "transparent", color: ORANGE, border: "none", borderRadius: 0, padding: "0", fontSize: 13.5, fontWeight: 400, textDecoration: "underline" },
  }[variant];
  return (
    <button onClick={onClick} disabled={disabled} title={title} style={{ ...styles, fontFamily: "Inter, sans-serif", cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1, display: "inline-flex", alignItems: "center", gap: 6 }}>
      {children}
    </button>
  );
}

// The backend has no endpoint for this action yet.
const NOT_CONNECTED = "Not connected to the backend yet";

// ─── Evidence graph panel ─────────────────────────────────────────────────────

function GraphPanel({ assessment }: { assessment: Assessment }) {
  const [mode, setMode] = useState<"Formal" | "Practice" | "Both">("Both");
  const [open, setOpen] = useState(false);

  const showFormal   = mode === "Formal"   || mode === "Both";
  const showPractice = mode === "Practice" || mode === "Both";

  const formal   = assessment.evidence.filter((item) => item.mode === "formal");
  const observed = assessment.evidence.filter((item) => item.mode === "observed");
  // People named on a visible attestation, each drawn once.
  const actors = [
    ...new Map(
      assessment.evidence
        .filter((item) => item.actor && (item.mode === "formal" ? showFormal : showPractice))
        .map((item) => [item.actor!.id, item.actor!]),
    ).values(),
  ];

  // ── Layout constants ──────────────────────────────────────────────────────
  // All coordinates are SVG user-units. Sources stack in a column either side
  // of the central Fact; node widths are derived from label length.
  const W = 860;
  const NH = 36;  // node height, all nodes
  const ROW = 56; // vertical distance between stacked sources
  const TOP = 40;

  const rows     = Math.max(formal.length, observed.length, 1);
  const rowsEnd  = TOP + (rows - 1) * ROW;
  const central  = { x: 430, y: (TOP + rowsEnd) / 2 };
  const actorY   = rowsEnd + 92;
  const H        = actors.length ? actorY + NH / 2 + 28 : rowsEnd + NH / 2 + 16;
  const leftX    = 110;
  const rightX   = 750;

  const widthOf   = (label: string) => label.length * 7 + 26;
  const central_w = widthOf(assessment.label);
  const columnY   = (i: number, n: number) => central.y + (i - (n - 1) / 2) * ROW;
  const fan       = (i: number, n: number) => (i - (n - 1) / 2) * 8;

  // Edge connection points (node surfaces, not centres)
  const cLeft   = central.x - central_w / 2;
  const cRight  = central.x + central_w / 2;
  const cBottom = central.y + NH / 2;

  // ── Helpers ───────────────────────────────────────────────────────────────

  // Renders a node rectangle + centred label. Text is guaranteed to fit
  // inside because w is computed from label length above.
  const node = (
    key: string, cx: number, cy: number, label: string,
    nw: number,
    opts: { dim?: boolean; dashed?: boolean; mono?: boolean } = {}
  ) => (
    <g key={key} opacity={opts.dim ? 0.45 : 1}>
      <rect
        x={cx - nw / 2} y={cy - NH / 2}
        width={nw} height={NH} rx={6}
        fill={opts.dim ? "#fafafa" : SURFACE}
        stroke={opts.dim ? "#d4d0ca" : "#d1cdc7"}
        strokeWidth={1.2}
        strokeDasharray={opts.dashed ? "5 3" : undefined}
      />
      <text
        x={cx} y={cy + 0.5}
        textAnchor="middle" dominantBaseline="middle"
        fontSize={opts.mono ? 10.5 : 11.5}
        fontFamily={opts.mono ? "JetBrains Mono, monospace" : "Inter, sans-serif"}
        fontWeight={opts.mono ? 500 : 400}
        fill={opts.dim ? "#aaa9a5" : "#2d2d2d"}
      >
        {label}
      </text>
    </g>
  );

  // Renders an edge line with an optional floating label on a white pill
  const edgeLine = (
    key: string,
    x1: number, y1: number, x2: number, y2: number,
    style: "solid" | "dashed" | "dotted",
    opts: { color?: string; label?: string; labelDy?: number } = {}
  ) => {
    const da    = style === "dashed" ? "7 4" : style === "dotted" ? "2 4" : undefined;
    const color = opts.color ?? "#c8c4be";
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const dy = opts.labelDy ?? 0;
    const lx = mx, ly = my + dy;
    return (
      <g key={key}>
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={1.3} strokeDasharray={da} />
        {opts.label && (
          <g>
            {/* white pill behind the label so it never overlaps line/nodes */}
            <rect
              x={lx - (opts.label.length * 3.3 + 8)} y={ly - 7}
              width={opts.label.length * 6.6 + 16} height={14}
              rx={3} fill={SURFACE}
            />
            <text
              x={lx} y={ly + 0.5}
              textAnchor="middle" dominantBaseline="middle"
              fontSize={9.5} fontFamily="Inter, sans-serif" fill={MUTED}
            >
              {opts.label}
            </text>
          </g>
        )}
      </g>
    );
  };

  // Non-material and out-of-scope sources stay on the graph, dimmed: never discarded.
  const sourceEdge = (item: Evidence, i: number, n: number, side: "left" | "right") => {
    const y = columnY(i, n);
    const half = widthOf(item.document.short_id) / 2;
    const label = item.applicable ? STANCE_WORD[item.stance].toLowerCase() : "out of scope";
    const color = item.material ? undefined : "#dedad4";
    return side === "left"
      ? edgeLine(`e-${item.edge_id}`, leftX + half, y, cLeft, central.y + fan(i, n), "solid", { color, label, labelDy: -9 })
      : edgeLine(`e-${item.edge_id}`, cRight, central.y + fan(i, n), rightX - half, y, "dashed", { color, label, labelDy: -9 });
  };
  const sourceNode = (item: Evidence, i: number, n: number, x: number) =>
    node(`n-${item.edge_id}`, x, columnY(i, n), item.document.short_id, widthOf(item.document.short_id), { mono: true, dim: !item.material, dashed: !item.material });
  const actorX = (i: number) => central.x + (i - (actors.length - 1) / 2) * 250;

  // ── Collapsed trigger row ─────────────────────────────────────────────────

  const chevronRight = (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0 }}>
      <path d="M5 3l4 4-4 4" stroke={MUTED} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
  const chevronDown = (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0 }}>
      <path d="M3 5l4 4 4-4" stroke={MUTED} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );

  const triggerRow = (isOpen: boolean) => (
    <div
      onClick={() => setOpen(!isOpen)}
      style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "0 24px", height: 56,
        background: SURFACE,
        borderBottom: isOpen ? `1px solid ${BORDER}` : "none",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "#faf9f7")}
      onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = SURFACE)}
    >
      {isOpen ? chevronDown : chevronRight}
      <span style={{ fontSize: 14, fontWeight: 500, color: TEXT, flex: 1 }}>Evidence graph</span>
      <span style={{ fontSize: 12.5, color: MUTED }}>{assessment.evidence.length} sources · {formal.length} formal · {observed.length} observed</span>
      <span style={{ fontSize: 12, color: MUTED, marginLeft: 20 }}>{isOpen ? "Hide" : "Show"}</span>
    </div>
  );

  // ── Graph body ────────────────────────────────────────────────────────────

  const graphBody = (
    <div style={{ padding: "20px 32px 32px" }}>
      {/* Toggle */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 20 }}>
        <div style={{ display: "inline-flex", border: `1px solid ${BORDER}`, borderRadius: 6, overflow: "hidden" }}>
          {(["Formal", "Practice", "Both"] as const).map((m) => (
            <button
              key={m}
              onClick={(e) => { e.stopPropagation(); setMode(m); }}
              style={{
                padding: "6px 16px", fontSize: 12, fontFamily: "Inter, sans-serif",
                background: mode === m ? "#f0ede8" : SURFACE,
                color: mode === m ? TEXT : MUTED,
                border: "none", borderRight: m !== "Both" ? `1px solid ${BORDER}` : "none",
                cursor: "pointer", fontWeight: mode === m ? 500 : 400,
              }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* SVG */}
      <div style={{ position: "relative" }}>
        <svg
          width="100%" viewBox={`0 0 ${W} ${H}`}
          style={{ display: "block", overflow: "visible" }}
          aria-label="Evidence graph"
        >
          {/* ── Edges (drawn before nodes so nodes paint over endpoints) ── */}

          {/* formal sources → central  |  solid */}
          {showFormal && formal.map((item, i) => sourceEdge(item, i, formal.length, "left"))}

          {/* central → observed sources  |  dashed */}
          {showPractice && observed.map((item, i) => sourceEdge(item, i, observed.length, "right"))}

          {/* central → named actors  |  dotted */}
          {actors.map((actor, i) => edgeLine(`e-${actor.id}`, central.x + fan(i, actors.length), cBottom, actorX(i), actorY - NH / 2, "dotted"))}

          {/* ── Nodes (painted on top of edges) ── */}

          {node("n-central", central.x, central.y, assessment.label, central_w)}
          {showFormal && formal.map((item, i) => sourceNode(item, i, formal.length, leftX))}
          {showPractice && observed.map((item, i) => sourceNode(item, i, observed.length, rightX))}
          {actors.map((actor, i) => (
            <g key={`n-${actor.id}`}>
              {node(`r-${actor.id}`, actorX(i), actorY, actor.label, widthOf(actor.label))}
              <text x={actorX(i)} y={actorY + NH / 2 + 14} textAnchor="middle" fontSize={9.5} fontFamily="Inter, sans-serif" fill={MUTED}>
                {actor.roles.join(", ") || "no role on record"}
              </text>
            </g>
          ))}
        </svg>

        {/* Legend */}
        <div style={{ marginTop: 20, display: "flex", gap: 24, alignItems: "center" }}>
          {([
            { da: undefined, label: "Formal source" },
            { da: "7 4",     label: "Observed practice" },
            { da: "2 4",     label: "Named actor" },
          ] as { da: string | undefined; label: string }[]).map(({ da, label }) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <svg width="28" height="10" style={{ flexShrink: 0 }}>
                <line x1="0" y1="5" x2="28" y2="5" stroke="#b0aca6" strokeWidth="1.5" strokeDasharray={da} />
              </svg>
              <span style={{ fontSize: 11.5, color: MUTED }}>{label}</span>
            </div>
          ))}
          <span style={{ fontSize: 11.5, color: MUTED }}>Dimmed · weighted down or out of scope, not discarded</span>
        </div>
      </div>
    </div>
  );

  return (
    <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden" }}>
      {triggerRow(open)}
      {open && graphBody}
    </div>
  );
}

// ─── Screen 1: Dashboard ──────────────────────────────────────────────────────

const VERDICT_FILTERS = ["Supported", "Contested", "Contradicted", "Insufficient evidence"];

function RegisterDashboardScreen({ nav, asOf }: { nav: Nav; asOf: string }) {
  const { data, error } = useApi(() => getClaims(asOf), [asOf]);
  const [verdict, setVerdict] = useState("All");
  const [q, setQ] = useState("");

  if (!data) {
    return (
      <PageShell>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: TEXT, letterSpacing: "-0.02em", margin: "0 0 28px" }}>Register results · recalculated</h1>
        <LoadState error={error} />
      </PageShell>
    );
  }

  const { summary, claims } = data;
  const empty = claims.length === 0;
  const rows = claims.filter((row) => {
    if (verdict !== "All" && row.formal_outcome !== verdict && row.observed_outcome !== verdict) return false;
    return !q || row.statement.toLowerCase().includes(q.toLowerCase());
  });

  return (
    <PageShell>
      <h1 style={{ fontSize: 20, fontWeight: 600, color: TEXT, letterSpacing: "-0.02em", margin: "0 0 28px" }}>Register results · recalculated</h1>

      {/* Tiles: Contested + Insufficient evidence prominent first, then secondary pair smaller */}
      <div style={{ display: "flex", gap: 12, marginBottom: 40 }}>
        {/* Primary tiles — larger number */}
        {[{ n: summary.contested, label: "Contested" }, { n: summary.insufficient_evidence, label: "Insufficient evidence" }].map(({ n, label }) => (
          <div key={label} style={{ flex: 1, padding: "28px 32px", background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8 }}>
            <div style={{ fontSize: 52, fontWeight: 700, color: empty ? MUTED : TEXT, letterSpacing: "-0.05em", lineHeight: 1, marginBottom: 8 }}>{n}</div>
            <div style={{ fontSize: 13, color: MUTED }}>{label}</div>
          </div>
        ))}
        {/* Secondary tiles — smaller number */}
        {[{ n: summary.claims_assessed, label: "Claims assessed" }, { n: summary.sources, label: "Sources" }].map(({ n, label }) => (
          <div key={label} style={{ flex: 1, padding: "28px 32px", background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8 }}>
            <div style={{ fontSize: 34, fontWeight: 600, color: empty ? MUTED : "#6b7280", letterSpacing: "-0.03em", lineHeight: 1, marginBottom: 8 }}>{n}</div>
            <div style={{ fontSize: 12.5, color: MUTED }}>{label}</div>
          </div>
        ))}
      </div>

      {empty ? (
        <EmptyDashboardState onCheck={() => nav.go("check")} />
      ) : (
        <>
          {/* Recent assessments heading + filters */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: TEXT }}>Current register results (not saved snapshots)</div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <a href={registerCsvUrl(asOf)} style={{ padding: "6px 10px", background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 6, fontSize: 12.5, color: TEXT3, textDecoration: "none" }}>
                Export CSV
              </a>
              <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 6, cursor: "pointer", fontSize: 12.5, color: TEXT3 }}>
                {verdict === "All" ? "Verdict" : verdict} <IcoChevron />
                <select
                  aria-label="Verdict"
                  value={verdict}
                  onChange={(e) => setVerdict(e.target.value)}
                  style={{ position: "absolute", inset: 0, width: "100%", opacity: 0, cursor: "pointer" }}
                >
                  <option value="All">All verdicts</option>
                  {VERDICT_FILTERS.map((option) => <option key={option}>{option}</option>)}
                </select>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 6, width: 210 }}>
                <IcoSearch />
                <input type="text" placeholder="Search claims…" value={q} onChange={(e) => setQ(e.target.value)} style={{ border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: TEXT, fontFamily: "Inter, sans-serif", width: "100%" }} />
              </div>
            </div>
          </div>

          {/* Rows — hairline dividers, no cards
              Grid: claim ~60% · formal 172px · practice 160px · date 92px */}
          <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden" }}>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 172px 160px 92px", padding: "9px 20px", borderBottom: `1px solid ${BORDER}`, background: "#faf9f7" }}>
              {["Claim", "Formal verdict", "In practice", "As at"].map((h) => (
                <div key={h} style={{ fontSize: 11, color: MUTED, fontWeight: 500 }}>{h}</div>
              ))}
            </div>
            {rows.length === 0 && (
              <div style={{ padding: "48px 20px", textAlign: "center", color: MUTED, fontSize: 13.5 }}>No claims match this filter.</div>
            )}
            {rows.map((row, i) => (
              <div
                key={row.fact_id}
                onClick={() => nav.openClaim(row.fact_id)}
                style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 172px 160px 92px", alignItems: "center", padding: "13px 20px", borderBottom: i < rows.length - 1 ? `1px solid ${BORDER_INNER}` : "none", cursor: "pointer" }}
                onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "#faf9f7")}
                onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "transparent")}
              >
                <div style={{ fontSize: 13.5, color: TEXT, lineHeight: 1.4, paddingRight: 24 }}>{row.statement}</div>
                <div><VerdictBadge verdict={row.formal_outcome.toLowerCase() as VerdictLabel} /></div>
                <div><VerdictBadge verdict={row.observed_outcome.toLowerCase() as VerdictLabel} /></div>
                <div style={{ fontSize: 12, color: MUTED }}>{fmtDate(data.as_of)}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </PageShell>
  );
}

// ─── Dashboard empty state ────────────────────────────────────────────────────

function EmptyDashboardState({ onCheck }: { onCheck: () => void }) {
  return (
    <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "80px 48px", display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
      {/* Simple illustration — abstract document icon */}
      <div style={{ width: 56, height: 56, borderRadius: 12, background: `${ORANGE}12`, border: `1px solid ${ORANGE}25`, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20 }}>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <rect x="4" y="2" width="16" height="20" rx="2" stroke={ORANGE} strokeWidth="1.5" />
          <path d="M8 7h8M8 11h8M8 15h5" stroke={ORANGE} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>
      <div style={{ fontSize: 16, fontWeight: 500, color: TEXT, marginBottom: 8 }}>No claims assessed yet</div>
      <div style={{ fontSize: 13.5, color: MUTED, maxWidth: 380, lineHeight: 1.6, marginBottom: 28 }}>
        Check your first claim to see how it holds up against your organisation's sources and documented authority.
      </div>
      <button
        onClick={onCheck}
        style={{ padding: "10px 22px", fontSize: 13.5, fontWeight: 500, fontFamily: "Inter, sans-serif", color: "#fff", background: ORANGE, border: "none", borderRadius: 6, cursor: "pointer" }}
      >
        Check a claim
      </button>
    </div>
  );
}

// ─── Screen 2: Check a claim ──────────────────────────────────────────────────

export function CheckScreen({ nav }: { nav: Nav }) {
  const [text, setText] = useState("");
  const [assessmentDate, setAssessmentDate] = useState(todayIso);
  const ready = text.trim().length > 0 && text.length <= 10000 && /^\d{4}-\d{2}-\d{2}$/.test(assessmentDate);

  return (
    <PageShell>
      <div style={{ maxWidth: 640 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: TEXT }}>Check a claim</h1>
        <p style={{ color: TEXT2, lineHeight: 1.6 }}>
          Enter a statement about how the organisation operates. It is assessed against
          the indexed sources, and every finding links to the original passage.
        </p>
        <label htmlFor="corpus-claim" style={{ display: "block", marginBottom: 8 }}>
          Your claim
        </label>
        <textarea
          id="corpus-claim"
          value={text}
          maxLength={10000}
          onChange={(event) => setText(event.target.value)}
          placeholder="Discounts of 15% or more require Finance approval before closing."
          style={{
            boxSizing: "border-box", width: "100%", minHeight: 140,
            padding: 14, font: "inherit", lineHeight: 1.6,
            color: TEXT, background: SURFACE,
            border: `1px solid ${BORDER}`, borderRadius: 6,
            resize: "vertical", marginBottom: 16,
          }}
        />
        <label htmlFor="claim-date" style={{display: "block", fontSize: 11.5, color: MUTED, marginBottom: 6}}>Assess as of</label>
        <input id="claim-date" type="date" required value={assessmentDate} onChange={event => setAssessmentDate(event.target.value)}
          style={{display: "block", width: 200, padding: "8px 12px", fontSize: 13.5, fontFamily: "Inter, sans-serif", color: TEXT, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 6, outline: "none"}} />
        <p style={{color: MUTED, fontSize: 12, margin: "8px 0 24px"}}>Choose when the claim should hold. Source dates and role authority will still need supporting evidence.</p>
        <Btn disabled={!ready} onClick={() => nav.checkClaim(text, assessmentDate)}>
          Check claim
        </Btn>
      </div>
    </PageShell>
  );
}

// ─── Screen 3: Assessment result ─────────────────────────────────────────────

// Out-of-scope sources stay visible but are never scored or counted towards a verdict.
const outOfScopeNote = (count: number) => `${count} out of scope`;

function laneSub(evidence: Evidence[], mode: Mode) {
  const lane = evidence.filter((item) => item.mode === mode);
  const inScope = lane.filter((item) => item.applicable);
  const decisive = inScope.filter((item) => item.material && item.stance !== "qualify");
  const setAside = lane.length > inScope.length ? ` · ${outOfScopeNote(lane.length - inScope.length)}` : "";
  if (decisive.length === 0) return `No qualifying sources found${setAside}`;
  return `${decisive.map((item) => item.document.short_id).join(", ")} · ${decisive.length} of ${inScope.length} sources material${setAside}`;
}

function TextListCard({ title, items }: { title: string; items: string[] }) {
  return (
    <div style={{ flex: 1, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden" }}>
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${BORDER}` }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: TEXT }}>{title}</div>
      </div>
      {items.map((text, i) => (
        <div key={i} style={{ padding: "12px 20px", fontSize: 13, color: TEXT2, lineHeight: 1.5, borderBottom: i < items.length - 1 ? `1px solid ${BORDER_INNER}` : "none" }}>{text}</div>
      ))}
    </div>
  );
}

function AssessmentScreen({ nav, target, asOf }: { nav: Nav; target: ClaimTarget; asOf: string }) {
  const key = target.kind === "fact" ? target.factId : target.text;
  const { data, error } = useApi<CheckResponse>(
    () =>
      target.kind === "query"
        ? checkClaim(target.text, asOf)
        : getClaim(target.factId, asOf).then((assessment) => ({
            claim: null, as_of: assessment.as_of, sources_searched: assessment.sources_searched, matches: [], assessment,
          })),
    [target.kind, key, asOf],
  );
  const assessment = data?.assessment ?? null;

  const header = (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
      <div style={{ fontSize: 12, color: MUTED }}>Claims / Assessment</div>
      <div style={{ display: "flex", gap: 8 }}>
        <Btn variant="secondary" disabled={!assessment} onClick={() => assessment && downloadJson(`${assessment.fact_id.replace(":", "-")}-assessment.json`, assessment)}>Export</Btn>
        <Btn onClick={() => nav.go("check")}>Run again</Btn>
      </div>
    </div>
  );

  if (!data) {
    return (
      <div style={{ flex: 1, overflowY: "auto", padding: "36px 48px" }}>
        {header}
        <LoadState error={error} />
      </div>
    );
  }

  // Nothing in the graph resembles the claim: a considered answer, not an error.
  if (!assessment) {
    return (
      <div style={{ flex: 1, overflowY: "auto", padding: "36px 48px" }}>
        {header}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <ClaimCard claimText={data.claim ?? ""} chips={[{ key: "as at", value: fmtDate(data.as_of) }]} />

          <VerdictCardPair
            left={{ label: "Formally", value: "Insufficient evidence", color: MUTED, sub: "No qualifying sources found" }}
            right={{ label: "In practice", value: "Insufficient evidence", color: MUTED, sub: "No qualifying sources found" }}
          />

          <ConfidenceBar pct={0} label="Not assessed" note={`${data.sources_searched} sources searched, 0 qualifying`} />

          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: TEXT, marginBottom: 12 }}>Evidence</div>
            <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "52px 48px", minHeight: 200 }}>
              <p style={{ fontSize: 16, fontWeight: 500, color: TEXT2, margin: "0 0 6px", maxWidth: 460 }}>No documented authority found.</p>
              <p style={{ fontSize: 13.5, color: MUTED, margin: "0 0 24px", maxWidth: 460 }}>A broad search across all {data.sources_searched} sources also returned nothing.</p>
              <Btn variant="secondary" onClick={() => nav.go("sources")}>View search coverage</Btn>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const confidence = CONFIDENCE[assessment.confidence] ?? { label: assessment.confidence, pct: 0 };
  const inScope = assessment.evidence.filter((item) => item.applicable).length;
  const material = assessment.evidence.filter((item) => item.material).length;
  const outOfScope = assessment.evidence.length - inScope;
  const confidenceNote = `${inScope} sources, ${material} material${outOfScope ? `, ${outOfScopeNote(outOfScope)}` : ""}`;
  const chips = [
    { key: "category", value: assessment.category },
    ...(assessment.scope ? [{ key: "scope", value: assessment.scope }] : []),
    { key: "as at", value: fmtDate(assessment.as_of) },
  ];
  const matched = data.matches[0];
  const alternatives = data.matches.slice(1);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "36px 48px" }}>
      {header}

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <ClaimCard
          claimText={assessment.statement}
          chips={chips}
          note={data.claim && matched ? `Closest documented fact to “${data.claim}” (similarity ${matched.similarity.toFixed(2)}). The verdicts below assess this fact as worded here.` : undefined}
        >
          {alternatives.length > 0 && (
            <div style={{ marginTop: 14, paddingTop: 12, borderTop: `1px solid ${BORDER_INNER}`, display: "flex", gap: 14, flexWrap: "wrap", alignItems: "baseline" }}>
              <span style={{ fontSize: 11.5, color: MUTED }}>Other matches</span>
              {alternatives.map((match) => (
                <button key={match.fact_id} onClick={() => nav.openClaim(match.fact_id)} style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 12.5, color: ORANGE, fontFamily: "Inter, sans-serif", textDecoration: "underline", textUnderlineOffset: 2 }}>
                  {match.label} ({match.similarity.toFixed(2)})
                </button>
              ))}
            </div>
          )}
        </ClaimCard>

        <VerdictCardPair
          left={{ label: "Formally", value: assessment.formal_outcome, color: outcomeColor(assessment.formal_outcome), sub: laneSub(assessment.evidence, "formal") }}
          right={{ label: "In practice", value: assessment.observed_outcome, color: outcomeColor(assessment.observed_outcome), sub: laneSub(assessment.evidence, "observed") }}
        />

        <ConfidenceBar pct={confidence.pct} label={confidence.label} note={confidenceNote} />

        {assessment.evidence.length > 0 ? (
          <EvidenceList evidence={assessment.evidence} onRowClick={nav.openEvidence} />
        ) : (
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: TEXT, marginBottom: 12 }}>Evidence</div>
            <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "52px 48px", minHeight: 200 }}>
              <p style={{ fontSize: 16, fontWeight: 500, color: TEXT2, margin: "0 0 6px", maxWidth: 460 }}>No documented authority found.</p>
              <p style={{ fontSize: 13.5, color: MUTED, margin: "0 0 24px", maxWidth: 460 }}>No source among the {assessment.sources_searched} indexed attests to this fact.</p>
              <Btn variant="secondary" onClick={() => nav.go("sources")}>View search coverage</Btn>
            </div>
          </div>
        )}

        {(assessment.gaps.length > 0 || assessment.related_qualifiers.length > 0) && (
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
            {assessment.gaps.length > 0 && <TextListCard title="Evidence gaps" items={assessment.gaps} />}
            {assessment.related_qualifiers.length > 0 && <TextListCard title="Related qualifications" items={assessment.related_qualifiers} />}
          </div>
        )}

        {assessment.evidence.length > 0 && <GraphPanel assessment={assessment} />}
      </div>
    </div>
  );
}

// ─── Shared: source claims + lineage ──────────────────────────────────────────

function SourceClaims({ title, attestations, onOpen }: { title: string; attestations: SourceAttestation[]; onOpen: (factId: string) => void }) {
  return (
    <div style={{ flex: 1, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden" }}>
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${BORDER}` }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: TEXT }}>{title}</div>
      </div>
      {attestations.length === 0 && <div style={{ padding: "13px 20px", fontSize: 13, color: MUTED }}>No claims attested.</div>}
      {attestations.map((item, i) => (
        <div
          key={item.edge_id}
          onClick={() => onOpen(item.fact_id)}
          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "13px 20px", borderBottom: i < attestations.length - 1 ? `1px solid ${BORDER_INNER}` : "none", cursor: "pointer" }}
          onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "#faf9f7")}
          onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "transparent")}
        >
          <div>
            <div style={{ fontSize: 13.5, color: TEXT, lineHeight: 1.4 }}>{item.statement}</div>
            <div style={{ fontSize: 11.5, color: MUTED, marginTop: 3 }}>{item.mode} · {STANCE_WORD[item.stance].toLowerCase()}{!item.applicable ? " · out of scope" : item.material ? "" : " · weighted down"}</div>
          </div>
          <VerdictBadge verdict={item.overall_outcome.toLowerCase() as VerdictLabel} />
        </div>
      ))}
    </div>
  );
}

function LineageCard({ links }: { links: LineageLink[] }) {
  const mono: React.CSSProperties = { fontFamily: "JetBrains Mono, monospace", fontSize: 12, fontWeight: 500, color: TEXT2 };
  const self = <span style={{ fontSize: 12, color: MUTED }}>this source</span>;
  return (
    <div style={{ flex: 1, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden" }}>
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${BORDER}` }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: TEXT }}>Lineage</div>
      </div>
      {links.length === 0 && <div style={{ padding: "13px 20px", fontSize: 13, color: MUTED }}>No recorded relationships.</div>}
      {links.map((link, i) => {
        const other = <span style={mono}>{link.kind === "document" ? link.short_id : link.label}</span>;
        return (
          <div key={i} style={{ padding: "12px 20px", borderBottom: i < links.length - 1 ? `1px solid ${BORDER_INNER}` : "none" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              {link.direction === "outgoing" ? self : other}
              <span style={{ fontSize: 11.5, color: MUTED }}>— {words(link.relationship).toLowerCase()} →</span>
              {link.direction === "outgoing" ? other : self}
              {link.kind === "document" && link.status && <StatusPill label={link.status} variant={statusVariant(link.status)} />}
            </div>
            {link.reason && <div style={{ fontSize: 11.5, color: MUTED, marginTop: 4 }}>{link.reason}</div>}
          </div>
        );
      })}
    </div>
  );
}

function MetaStrip({ cols }: { cols: { label: string; value: string }[] }) {
  return (
    <div style={{ display: "flex", gap: 0, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden", marginBottom: 28 }}>
      {cols.map(({ label, value }, i) => (
        <div key={label} style={{ flex: 1, padding: "14px 18px", borderRight: i < cols.length - 1 ? `1px solid ${BORDER_INNER}` : "none" }}>
          <div style={{ fontSize: 10.5, color: MUTED, marginBottom: 5 }}>{label}</div>
          <div style={{ fontSize: 13.5, fontWeight: 500, color: TEXT }}>{value}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Screen 5: Evidence detail ────────────────────────────────────────────────

function EvidenceDetailScreen({ nav, evidence, asOf }: { nav: Nav; evidence: Evidence; asOf: string }) {
  const { data: source, error } = useApi(() => getSource(evidence.document_id, asOf), [evidence.document_id, asOf]);
  const doc = evidence.document;
  const dimensions = Object.entries(evidence.dimensions);

  const metaCols = [
    { label: "Lane", value: evidence.mode === "formal" ? "Formal" : "Observed practice" },
    { label: "Stance", value: STANCE_WORD[evidence.stance] },
    { label: "Source class", value: words(evidence.source_class) },
    { label: "Effective", value: fmtDate(doc.effective_date ?? doc.last_updated) },
    { label: "Materiality", value: evidence.materiality_score === null ? "Not scored" : `${evidence.materiality_score.toFixed(2)} · ${evidence.material ? "material" : "not material"}` },
  ];

  return (
    <PageShell>
      {/* Back link */}
      <button onClick={() => nav.go("assessment")} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, color: MUTED, padding: 0, marginBottom: 24, fontFamily: "Inter, sans-serif" }}>
        ← Back to assessment
      </button>

      {/* Heading */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <h1 style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 22, fontWeight: 600, color: TEXT, margin: 0, letterSpacing: "-0.01em" }}>{doc.short_id}</h1>
        <StatusPill label={evidence.lifecycle_status} variant={statusVariant(evidence.lifecycle_status)} />
      </div>
      <div style={{ fontSize: 13.5, color: TEXT3, marginBottom: 20 }}>{doc.title}</div>

      {/* Metadata strip */}
      <MetaStrip cols={metaCols} />

      {/* Attested value */}
      <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderLeft: `3px solid ${ORANGE}`, borderRadius: "0 8px 8px 0", padding: "24px 28px", marginBottom: 28 }}>
        <div style={{ fontSize: 10.5, color: MUTED, marginBottom: 14 }}>What this source attests</div>
        <p style={{ fontSize: 17, color: TEXT, lineHeight: 1.75, margin: 0 }}>{evidence.attests_value}</p>
        {evidence.actor && (
          <div style={{ fontSize: 12.5, color: TEXT3, marginTop: 14 }}>Named actor · {evidence.actor.label}{evidence.actor.roles.length > 0 && ` (${evidence.actor.roles.join(", ")})`}</div>
        )}
      </div>

      {/* Two columns: credibility dimensions + derivation trace */}
      <div style={{ display: "flex", gap: 24, marginBottom: 24, alignItems: "flex-start" }}>
        <div style={{ flex: 1, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: `1px solid ${BORDER}` }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: TEXT }}>Credibility dimensions</div>
          </div>
          {dimensions.length === 0 && <div style={{ padding: "13px 20px", fontSize: 13, color: MUTED }}>Not scored — the source is out of scope for this claim.</div>}
          {dimensions.map(([name, value], i) => (
            <div key={name} style={{ display: "grid", gridTemplateColumns: "170px 1fr 36px", alignItems: "center", gap: 14, padding: "11px 20px", borderBottom: i < dimensions.length - 1 ? `1px solid ${BORDER_INNER}` : "none" }}>
              <div style={{ fontSize: 12.5, color: TEXT2 }}>{typeLabel(name)}</div>
              <div style={{ height: 3, background: BORDER_INNER, borderRadius: 2 }}>
                <div style={{ width: `${Math.round(value * 100)}%`, height: "100%", background: "#9ca3af", borderRadius: 2 }} />
              </div>
              <div style={{ fontSize: 12, color: MUTED, fontFamily: "JetBrains Mono, monospace", textAlign: "right" }}>{value.toFixed(2)}</div>
            </div>
          ))}
        </div>

        <TextListCard title="Derivation trace" items={[...evidence.trace, ...evidence.limitations.map((text) => `Limitation: ${text}`)]} />
      </div>

      {/* Two columns: claims + lineage */}
      {source ? (
        <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
          <SourceClaims title="Claims this source attests" attestations={source.attestations} onOpen={nav.openClaim} />
          <LineageCard links={source.lineage} />
        </div>
      ) : (
        <LoadState error={error} />
      )}
    </PageShell>
  );
}

// Sample rows for the components page only; live rows come from /api/claims.
const CLAIM_ROWS: { text: string; formal: VerdictLabel; practice: VerdictLabel | null; date: string }[] = [
  { text: "Discounts of 15% or more require approval from the Head of Finance before closing.", formal: "supported", practice: "contested", date: "8 Sep 2026" },
  { text: "All client contracts above $500k must be reviewed by Legal before signature.",        formal: "supported", practice: "supported", date: "5 Sep 2026" },
];

// ─── Screen 6: Components page ────────────────────────────────────────────────

function ComponentsScreen() {
  const [conf, setConf] = useState(0);

  const Group = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div style={{ marginBottom: 40 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: MUTED, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 16, paddingBottom: 8, borderBottom: `1px solid ${BORDER}` }}>{title}</div>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>{children}</div>
    </div>
  );

  return (
    <PageShell>
      <h1 style={{ fontSize: 20, fontWeight: 600, color: TEXT, letterSpacing: "-0.02em", margin: "0 0 36px" }}>Components</h1>

      <Group title="Verdict badge">
        <VerdictBadge verdict="supported" />
        <VerdictBadge verdict="contested" />
        <VerdictBadge verdict="contradicted" />
        <VerdictBadge verdict="insufficient evidence" />
        <VerdictBadge verdict="no authority" />
      </Group>

      <Group title="Status pill">
        <StatusPill label="approved" variant="green" />
        <StatusPill label="superseded" variant="grey" />
        <StatusPill label="draft" variant="amber" />
        <StatusPill label="not revised since 2022" variant="amber" />
      </Group>

      <Group title="Evidence row">
        {[
          { icon: <IcoPlus />, label: "Supports", id: "POL-01 §3", pill: { label: "approved", v: "green" as PillVariant }, meta: "v3 · from 2025-03-01", desc: "Supports · policy, in force" },
          { icon: <IcoMinus />, label: "Contradicts", id: "PROC-02", pill: { label: "not revised since 2022", v: "amber" as PillVariant }, meta: "", desc: "Names a different approver · weighted down, not discarded" },
          { icon: <IcoMerge />, label: "Grouped", id: "COMMS-02 → 03 → 04", pill: { label: "counted once", v: "grey" as PillVariant }, meta: "", desc: "One origin, relayed twice · MTG-02" },
        ].map((row) => (
          <div key={row.label} style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "14px 18px", width: 420 }}>
            <div style={{ fontSize: 10.5, color: MUTED, marginBottom: 10, fontWeight: 500 }}>{row.label}</div>
            <div style={{ display: "flex", gap: 12, alignItems: "start" }}>
              <div style={{ paddingTop: 1 }}>{row.icon}</div>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, fontWeight: 500, color: TEXT2 }}>{row.id}</span>
                  <StatusPill label={row.pill.label} variant={row.pill.v} />
                  {row.meta && <span style={{ fontSize: 11.5, color: MUTED }}>{row.meta}</span>}
                </div>
                <div style={{ fontSize: 12.5, color: TEXT3 }}>{row.desc}</div>
              </div>
            </div>
          </div>
        ))}
      </Group>

      <Group title="Confidence bar">
        {([["Low", 18], ["Medium", 55], ["High", 88]] as [string, number][]).map(([label, pct]) => (
          <div key={label} style={{ width: 280 }}>
            <ConfidenceBar pct={pct} label={label} note={`${pct}%`} />
          </div>
        ))}
      </Group>

      <Group title="Claim row">
        <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden", width: "100%", maxWidth: 860 }}>
          {CLAIM_ROWS.slice(0, 2).map((row, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 148px 148px 96px", alignItems: "center", padding: "13px 20px", borderBottom: i === 0 ? `1px solid ${BORDER_INNER}` : "none" }}>
              <div style={{ fontSize: 13.5, color: TEXT, lineHeight: 1.4, paddingRight: 28 }}>{row.text}</div>
              <div><VerdictBadge verdict={row.formal} /></div>
              <div>{row.practice ? <VerdictBadge verdict={row.practice} /> : <span style={{ fontSize: 12, color: "#d1d5db" }}>—</span>}</div>
              <div style={{ fontSize: 12, color: MUTED }}>{row.date}</div>
            </div>
          ))}
        </div>
      </Group>

      <Group title="Buttons">
        <Btn>Primary orange</Btn>
        <Btn variant="secondary">Secondary outlined</Btn>
        <Btn variant="link">Text link</Btn>
      </Group>

      <Group title="Form fields">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={{ display: "block", fontSize: 11.5, color: MUTED, marginBottom: 6 }}>Text field</label>
            <input type="text" placeholder="Enter a claim statement…" style={{ width: 340, padding: "8px 12px", fontSize: 13.5, fontFamily: "Inter, sans-serif", color: TEXT, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 6, outline: "none" }} />
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11.5, color: MUTED, marginBottom: 6 }}>Date field</label>
            <input type="text" defaultValue="Today" style={{ width: 200, padding: "8px 12px", fontSize: 13.5, fontFamily: "Inter, sans-serif", color: TEXT, background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 6, outline: "none" }} />
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11.5, color: MUTED, marginBottom: 6 }}>Dropdown</label>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 12px", background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 6, cursor: "pointer", fontSize: 13.5, color: TEXT3, width: 200 }}>
              <span style={{ flex: 1 }}>Verdict</span>
              <IcoChevron />
            </div>
          </div>
        </div>
      </Group>

      {/* Interactive demo */}
      <Group title="Interactive — confidence bar">
        <div style={{ width: "100%", maxWidth: 500 }}>
          <input type="range" min={0} max={100} value={conf} onChange={(e) => setConf(+e.target.value)} style={{ width: "100%", marginBottom: 12, accentColor: ORANGE }} />
          <ConfidenceBar pct={conf} label={conf < 30 ? "Low" : conf < 65 ? "Medium" : "High"} note={`${conf}%`} />
        </div>
      </Group>
    </PageShell>
  );
}

// ─── Screens: sign in, sign up, forgot and reset password ─────────────────────

const MIN_PASSWORD = 8;

function AuthShell({ subtitle, children, footer }: { subtitle: string; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <div style={{
      minHeight: "100%", background: PAGE,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{ width: 400 }}>
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: 40 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: TEXT, letterSpacing: "-0.03em", marginBottom: 6 }}>
            Claim checker
          </div>
          <div style={{ fontSize: 13.5, color: MUTED }}>{subtitle}</div>
        </div>

        <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "32px 32px 28px" }}>
          {children}
        </div>

        {footer && <div style={{ textAlign: "center", marginTop: 20, fontSize: 12.5, color: MUTED }}>{footer}</div>}
      </div>
    </div>
  );
}

function AuthField({ label, value, onChange, type = "text", placeholder = "", autoComplete }: { label: string; value: string; onChange: (v: string) => void; type?: string; placeholder?: string; autoComplete?: string }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: "block", fontSize: 12, color: MUTED, marginBottom: 6, fontWeight: 500 }}>
        {label}
        <input
          type={type}
          value={value}
          placeholder={placeholder}
          autoComplete={autoComplete}
          onChange={(e) => onChange(e.target.value)}
          style={{
            display: "block", width: "100%", padding: "10px 12px", fontSize: 14, marginTop: 6,
            fontFamily: "Inter, sans-serif", color: TEXT, fontWeight: 400,
            background: SURFACE, border: `1px solid ${BORDER}`,
            borderRadius: 6, outline: "none",
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = ORANGE)}
          onBlur={(e) => (e.currentTarget.style.borderColor = BORDER)}
        />
      </label>
    </div>
  );
}

function AuthMessage({ text, tone }: { text: string | null; tone: "error" | "notice" }) {
  if (!text) return null;
  const s = tone === "error" ? { color: RED_TEXT, bg: RED_BG, border: `${RED_TEXT}25` } : { color: GREEN_TEXT, bg: GREEN_BG, border: `${GREEN_TEXT}25` };
  return (
    <div role={tone === "error" ? "alert" : "status"} style={{ fontSize: 12.5, lineHeight: 1.5, color: s.color, background: s.bg, border: `1px solid ${s.border}`, borderRadius: 6, padding: "9px 12px", marginBottom: 16 }}>
      {text}
    </div>
  );
}

function AuthSubmit({ children, busy }: { children: React.ReactNode; busy: boolean }) {
  return (
    <button
      type="submit" disabled={busy}
      style={{
        width: "100%", padding: "11px 0", fontSize: 14, fontWeight: 500,
        fontFamily: "Inter, sans-serif", color: "#fff",
        background: ORANGE, border: "none", borderRadius: 6,
        cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
      }}
    >
      {children}
    </button>
  );
}

function AuthLink({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{ background: "none", border: "none", fontSize: 12.5, color: ORANGE, cursor: "pointer", fontFamily: "Inter, sans-serif", padding: 0 }}>
      {children}
    </button>
  );
}

// Runs a form submission, tracking the busy state and surfacing the API's error text.
function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = (event: React.FormEvent, action: () => Promise<void>, invalid?: string | null) => {
    event.preventDefault();
    if (invalid) return setError(invalid);
    setBusy(true);
    setError(null);
    action().catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  return { busy, error, submit };
}

function passwordProblem(password: string, confirm: string) {
  if (password.length < MIN_PASSWORD) return `Password must be at least ${MIN_PASSWORD} characters.`;
  if (password !== confirm) return "The two passwords do not match.";
  return null;
}

function LoginScreen({ setScreen, onSignedIn, notice }: { setScreen: (s: Screen) => void; onSignedIn: (user: User) => void; notice: string | null }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, submit } = useSubmit();

  return (
    <AuthShell
      subtitle="Sign in to your workspace"
      footer={<>Don't have an account?{" "}<AuthLink onClick={() => setScreen("signup")}>Request access</AuthLink></>}
    >
      <form onSubmit={(e) => submit(e, () => login(email, password).then(onSignedIn), !email || !password ? "Enter your email and password." : null)}>
        <AuthMessage text={error ? null : notice} tone="notice" />
        <AuthMessage text={error} tone="error" />
        <AuthField label="Email address" value={email} onChange={setEmail} type="email" placeholder="you@company.com" autoComplete="username" />
        <AuthField label="Password" value={password} onChange={setPassword} type="password" placeholder="••••••••" autoComplete="current-password" />

        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 24, marginTop: -8 }}>
          <AuthLink onClick={() => setScreen("forgot")}>Forgot password?</AuthLink>
        </div>

        <AuthSubmit busy={busy}>Sign in</AuthSubmit>
      </form>
    </AuthShell>
  );
}

function SignupScreen({ setScreen, onSignedIn }: { setScreen: (s: Screen) => void; onSignedIn: (user: User) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const { busy, error, submit } = useSubmit();
  const invalid = !name.trim() || !email ? "Enter your name and email address." : passwordProblem(password, confirm);

  return (
    <AuthShell
      subtitle="Create your account"
      footer={<>Already have an account?{" "}<AuthLink onClick={() => setScreen("login")}>Sign in</AuthLink></>}
    >
      <form onSubmit={(e) => submit(e, () => signup(name.trim(), email, password).then(onSignedIn), invalid)}>
        <AuthMessage text={error} tone="error" />
        <AuthField label="Full name" value={name} onChange={setName} placeholder="Jordan Ramirez" autoComplete="name" />
        <AuthField label="Email address" value={email} onChange={setEmail} type="email" placeholder="you@company.com" autoComplete="username" />
        <AuthField label={`Password (at least ${MIN_PASSWORD} characters)`} value={password} onChange={setPassword} type="password" autoComplete="new-password" />
        <AuthField label="Confirm password" value={confirm} onChange={setConfirm} type="password" autoComplete="new-password" />
        <div style={{ height: 8 }} />
        <AuthSubmit busy={busy}>Create account</AuthSubmit>
      </form>
    </AuthShell>
  );
}

function ForgotScreen({ setScreen }: { setScreen: (s: Screen) => void }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const { busy, error, submit } = useSubmit();

  return (
    <AuthShell subtitle="Reset your password" footer={<AuthLink onClick={() => setScreen("login")}>← Back to sign in</AuthLink>}>
      {sent ? (
        <>
          <div style={{ fontSize: 14, fontWeight: 500, color: TEXT, marginBottom: 8 }}>Check for your reset link</div>
          <div style={{ fontSize: 13, color: TEXT3, lineHeight: 1.6 }}>
            If an account exists for {email}, a reset link has been issued and is valid for one hour. This prototype has no email service, so the link is printed in the API terminal rather than sent.
          </div>
        </>
      ) : (
        <form onSubmit={(e) => submit(e, () => forgotPassword(email).then(() => setSent(true)), !email ? "Enter your email address." : null)}>
          <AuthMessage text={error} tone="error" />
          <AuthField label="Email address" value={email} onChange={setEmail} type="email" placeholder="you@company.com" autoComplete="username" />
          <div style={{ height: 8 }} />
          <AuthSubmit busy={busy}>Send reset link</AuthSubmit>
        </form>
      )}
    </AuthShell>
  );
}

function ResetScreen({ token, onDone, onCancel }: { token: string; onDone: () => void; onCancel: () => void }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const { busy, error, submit } = useSubmit();

  return (
    <AuthShell subtitle="Choose a new password" footer={<AuthLink onClick={onCancel}>← Back to sign in</AuthLink>}>
      <form onSubmit={(e) => submit(e, () => resetPassword(token, password).then(onDone), passwordProblem(password, confirm))}>
        <AuthMessage text={error} tone="error" />
        <AuthField label={`New password (at least ${MIN_PASSWORD} characters)`} value={password} onChange={setPassword} type="password" autoComplete="new-password" />
        <AuthField label="Confirm new password" value={confirm} onChange={setConfirm} type="password" autoComplete="new-password" />
        <div style={{ height: 8 }} />
        <AuthSubmit busy={busy}>Update password</AuthSubmit>
      </form>
    </AuthShell>
  );
}

// ─── Screen: Sources ──────────────────────────────────────────────────────────

const STATUS_STYLE: Record<PillVariant, { color: string; bg: string; border: string }> = {
  green: { color: GREEN_TEXT, bg: GREEN_BG, border: `${GREEN_TEXT}25` },
  amber: { color: AMBER_TEXT, bg: AMBER_BG, border: `${AMBER_TEXT}25` },
  grey:  { color: GREY_TEXT,  bg: GREY_BG,  border: BORDER },
};

// Source types come from the graph, so chip colours are assigned in order.
const TYPE_PALETTE = [
  { bg: "#dbeafe", text: "#1e40af" }, { bg: "#fef9c3", text: "#713f12" }, { bg: "#fce7f3", text: "#9d174d" },
  { bg: "#ede9fe", text: "#4c1d95" }, { bg: "#d1fae5", text: "#065f46" }, { bg: "#fee2e2", text: "#991b1b" },
];
const typeLabel = (type: string | null) => words(type ?? "unknown").replace(/^./, (c) => c.toUpperCase());

// Sources come from the corpus graph bundled with the app (see orgGraph.ts), not the
// prototype graph behind /api/sources.
const CORPUS_SOURCES = orgDocuments().map((doc) => ({
  id: doc.node.id, short_id: doc.shortId, title: doc.node.label, type: doc.sourceClass, status: doc.status,
  approval_status: doc.approval, last_updated: doc.date ?? null,
  governs: doc.governs.map((process) => process.attributes.code ?? process.label),
}));

export function SourcesScreen() {
  const sources = CORPUS_SOURCES;
  const [typeFilter, setTypeFilter] = useState("All");
  const [statusFilter, setStatusFilter] = useState("All");
  const [q, setQ] = useState("");

  const types = [...new Set(sources.map((s) => typeLabel(s.type)))].sort();
  const statuses = [...new Set(sources.map((s) => s.status))].sort();
  const typeColor = (type: string) => TYPE_PALETTE[types.indexOf(type) % TYPE_PALETTE.length];

  const filtered = sources.filter((s) => {
    if (typeFilter !== "All" && typeLabel(s.type) !== typeFilter) return false;
    if (statusFilter !== "All" && s.status !== statusFilter) return false;
    if (q && !s.title.toLowerCase().includes(q.toLowerCase()) && !s.short_id.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });

  return (
    <PageShell>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: TEXT, letterSpacing: "-0.02em", margin: "0 0 4px" }}>Sources</h1>
          <div style={{ fontSize: 13, color: MUTED }}>{sources.length} documents in the corpus graph</div>
        </div>
      </div>

      {/* Summary strip */}
      <div style={{ display: "flex", gap: 12, marginBottom: 28 }}>
        {[
          ...statuses.map((status) => ({ n: sources.filter((s) => s.status === status).length, label: typeLabel(status), color: STATUS_STYLE[statusVariant(status)].color })),
          { n: sources.filter((s) => s.governs.length > 0).length, label: "Govern a process", color: TEXT },
        ].map(({ n, label, color }) => (
          <div key={label} style={{ flex: 1, padding: "16px 20px", background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8 }}>
            <div style={{ fontSize: 28, fontWeight: 600, color, letterSpacing: "-0.03em", lineHeight: 1, marginBottom: 5 }}>{n}</div>
            <div style={{ fontSize: 12, color: MUTED }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        {/* Type filter */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, flexBasis: "100%" }}>
          {["All", ...types].map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              style={{
                padding: "5px 12px", fontSize: 12, fontFamily: "Inter, sans-serif", whiteSpace: "nowrap",
                background: typeFilter === t ? (t === "All" ? TEXT : typeColor(t).bg) : SURFACE,
                color: typeFilter === t ? (t === "All" ? "#fff" : typeColor(t).text) : TEXT3,
                border: `1px solid ${BORDER}`, borderRadius: 5, cursor: "pointer",
                fontWeight: typeFilter === t ? 500 : 400,
              }}
            >
              {t}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {/* Status filter */}
        {["All", ...statuses].map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            style={{
              padding: "5px 12px", fontSize: 12, fontFamily: "Inter, sans-serif", whiteSpace: "nowrap",
              background: statusFilter === s ? GREY_BG : SURFACE,
              color: statusFilter === s ? TEXT : MUTED,
              border: `1px solid ${statusFilter === s ? BORDER : "transparent"}`,
              borderRadius: 5, cursor: "pointer", fontWeight: statusFilter === s ? 500 : 400,
            }}
          >
            {s === "All" ? "All statuses" : typeLabel(s)}
          </button>
        ))}
        {/* Search */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 6, width: 220 }}>
          <IcoSearch />
          <input
            type="text" placeholder="Search sources…" value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: TEXT, fontFamily: "Inter, sans-serif", width: "100%" }}
          />
        </div>
      </div>

      {/* Table */}
      <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: "170px 1fr 216px 104px 96px 64px 96px", padding: "9px 20px", borderBottom: `1px solid ${BORDER}`, background: "#faf9f7" }}>
          {["ID", "Name", "Class", "Approval", "Dated", "Governs", "Status"].map((h) => (
            <div key={h} style={{ fontSize: 11, color: MUTED, fontWeight: 500 }}>{h}</div>
          ))}
        </div>
        {filtered.length === 0 && (
          <div style={{ padding: "48px 20px", textAlign: "center", color: MUTED, fontSize: 13.5 }}>No sources match this filter.</div>
        )}
        {filtered.map((src, i) => {
          const ss = STATUS_STYLE[statusVariant(src.status)];
          const tc = typeColor(typeLabel(src.type));
          return (
            <div
              key={src.id}
              style={{ display: "grid", gridTemplateColumns: "170px 1fr 216px 104px 96px 64px 96px", alignItems: "center", padding: "13px 20px", borderBottom: i < filtered.length - 1 ? `1px solid ${BORDER_INNER}` : "none" }}
            >
              <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11.5, fontWeight: 500, color: TEXT2, overflowWrap: "anywhere", paddingRight: 12 }}>{src.short_id}</span>
              <span style={{ fontSize: 13.5, color: TEXT, paddingRight: 16, lineHeight: 1.35 }}>{src.title}</span>
              <span>
                <span style={{ fontSize: 11, fontWeight: 500, padding: "2px 8px", borderRadius: 4, background: tc.bg, color: tc.text, whiteSpace: "nowrap" }}>{typeLabel(src.type)}</span>
              </span>
              <span style={{ fontSize: 12.5, color: TEXT3 }}>{typeLabel(src.approval_status)}</span>
              <span style={{ fontSize: 12, color: MUTED, fontFamily: "JetBrains Mono, monospace" }}>{fmtDate(src.last_updated)}</span>
              <span style={{ fontSize: 12.5, color: src.governs.length ? TEXT : MUTED }}>{src.governs.join(", ") || "—"}</span>
              <span>
                <span style={{ display: "inline-flex", alignItems: "center", fontSize: 11, fontWeight: 500, padding: "2px 8px", borderRadius: 4, color: ss.color, background: ss.bg, border: `1px solid ${ss.border}` }}>
                  {typeLabel(src.status)}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </PageShell>
  );
}

// ─── Screen: Settings ─────────────────────────────────────────────────────────

function SettingsScreen({ user, onUser }: { user: User; onUser: (user: User) => void }) {
  const [name, setName] = useState(user.name);
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "9px 12px", fontSize: 13.5,
    fontFamily: "Inter, sans-serif", color: TEXT,
    background: SURFACE, border: `1px solid ${BORDER}`,
    borderRadius: 6, outline: "none",
  };
  const labelStyle: React.CSSProperties = { display: "block", fontSize: 11.5, color: MUTED, marginBottom: 6, fontWeight: 500 };

  const field = (label: string, value: string, onChange: (v: string) => void, type = "text", autoComplete?: string) => (
    <div style={{ marginBottom: 18 }}>
      <label style={labelStyle}>{label}</label>
      <input type={type} value={value} autoComplete={autoComplete} aria-label={label} onChange={(e) => onChange(e.target.value)} style={inputStyle}
        onFocus={(e) => (e.currentTarget.style.borderColor = ORANGE)}
        onBlur={(e) => (e.currentTarget.style.borderColor = BORDER)} />
    </div>
  );

  const save = async () => {
    setSaved(false);
    setError(null);
    const changingPw = Boolean(currentPw || newPw || confirmPw);
    if (!name.trim()) return setError("Display name cannot be empty.");
    if (changingPw) {
      if (!currentPw) return setError("Enter your current password to change it.");
      const problem = passwordProblem(newPw, confirmPw);
      if (problem) return setError(problem);
    }
    try {
      if (name.trim() !== user.name) onUser(await updateProfile(name.trim()));
      if (changingPw) {
        await changePassword(currentPw, newPw);
        setCurrentPw(""); setNewPw(""); setConfirmPw("");
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <PageShell>
      <h1 style={{ fontSize: 20, fontWeight: 600, color: TEXT, letterSpacing: "-0.02em", margin: "0 0 32px" }}>Settings</h1>

      <div style={{ maxWidth: 480 }}>
        {/* Profile */}
        <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "28px 28px 24px", marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: TEXT, marginBottom: 20 }}>Profile</div>
          {field("Display name", name, setName)}
          <div style={{ marginBottom: 0 }}>
            <label style={labelStyle}>Email</label>
            <input type="email" value={user.email} readOnly style={{ ...inputStyle, color: MUTED, cursor: "default" }} />
          </div>
        </div>

        {/* Password */}
        <div style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, padding: "28px 28px 24px", marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: TEXT, marginBottom: 20 }}>Change password</div>
          {field("Current password", currentPw, setCurrentPw, "password", "current-password")}
          {field("New password", newPw, setNewPw, "password", "new-password")}
          {field("Confirm new password", confirmPw, setConfirmPw, "password", "new-password")}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Btn onClick={save}>Save changes</Btn>
          {saved && <span style={{ fontSize: 12.5, color: GREEN_TEXT }}>Saved</span>}
          {error && <span role="alert" style={{ fontSize: 12.5, color: RED_TEXT }}>{error}</span>}
        </div>
      </div>
    </PageShell>
  );
}


// ─── App ──────────────────────────────────────────────────────────────────────

const AUTH_SCREENS: Screen[] = ["login", "signup", "forgot"];

export default function App() {
  const [screen, setScreen] = useState<Screen>("login");
  // undefined while the session is being checked, null when signed out.
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [resetToken, setResetToken] = useState(() => new URLSearchParams(window.location.search).get("reset"));
  const [notice, setNotice] = useState<string | null>(null);
  const [asOf, setAsOf] = useState(todayIso);
  const [target, setTarget] = useState<ClaimTarget | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [savedRunId, setSavedRunId] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);

  const signedOut = (message: string | null = null) => {
    setUser(null);
    setNotice(message);
    setScreen("login");
    setTarget(null);
    setEvidence(null);
    setSourceId(null);
    setSavedRunId(null);
  };

  useEffect(() => {
    // A session that expires mid-use sends the user back to sign in.
    onUnauthorized(() => signedOut("Your session has ended. Sign in again to continue."));
    getMe().then(setUser, () => setUser(null));
  }, []);

  // Screens that need a selection fall back to the place where one is made.
  const go = (next: Screen) => {
    setNotice(null);
    if (next === "assessment" && !target) return setScreen("check");
    if (next === "evidence-detail" && !evidence) return setScreen(target ? "assessment" : "check");
    if (next === "source-detail" && !sourceId) return setScreen("sources");
    setScreen(next);
  };

  const nav: Nav = {
    go,
    openSaved: (runId) => { setSavedRunId(runId); setScreen("saved-assessment"); },
    openClaim: (factId) => { setTarget({ kind: "fact", factId }); setScreen("assessment"); },
    checkClaim: (text, selectedDate = todayIso()) => { setTarget({ kind: "query", text, asOf: selectedDate, run: Date.now() }); setScreen("assessment"); },
    openEvidence: (item) => { setEvidence(item); setScreen("evidence-detail"); },
    openSource: (documentId) => { setSourceId(documentId); setScreen("source-detail"); },
  };

  const signedIn = (next: User) => { setUser(next); setNotice(null); setScreen("dashboard"); };
  const clearReset = () => { setResetToken(null); window.history.replaceState(null, "", window.location.pathname); };

  if (user === undefined) return <div style={{ minHeight: "100%", background: PAGE }} />;

  if (resetToken) {
    return (
      <ResetScreen
        token={resetToken}
        onDone={() => { clearReset(); signedOut("Password updated. Sign in with your new password."); }}
        onCancel={clearReset}
      />
    );
  }

  if (!user) {
    if (screen === "signup") return <SignupScreen setScreen={go} onSignedIn={signedIn} />;
    if (screen === "forgot") return <ForgotScreen setScreen={go} />;
    return <LoginScreen setScreen={go} onSignedIn={signedIn} notice={notice} />;
  }

  const view = AUTH_SCREENS.includes(screen) ? "dashboard" : screen;

  return (
    <div style={{ minWidth: 900, height: "100%", display: "flex", background: PAGE }}>
      <Sidebar screen={view} setScreen={go} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <TopBar user={user} onSignOut={() => logout().finally(() => signedOut())} />

        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {view === "dashboard" && <PageShell><SavedDashboard onOpen={nav.openSaved} onCheck={() => nav.go("check")} /></PageShell>}
          {view === "register" && <RegisterDashboardScreen nav={nav} asOf={asOf} />}
          {view === "saved-assessment" && savedRunId && <PageShell><SavedAssessmentView key={savedRunId} runId={savedRunId} onBack={() => nav.go("dashboard")} onOpen={nav.openSaved} onRunAgain={nav.checkClaim} /></PageShell>}
          {view === "check" && <CheckScreen nav={nav} />}
          {/* A checked claim stays mounted while other pages are open, so coming back to Claims
              shows the same result instead of assessing it again. Only a new check replaces it. */}
          {target?.kind === "query" && (
            <div style={{ display: view === "assessment" ? "contents" : "none" }}>
              <CorpusScreen
                key={target.run}
                claim={target.text}
                initialAsOf={target.asOf}
                onBack={() => { setTarget(null); setScreen("check"); }}
              />
            </div>
          )}
          {view === "assessment" && target?.kind === "fact" && (
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
              <label style={{ padding: "16px 48px 0", fontSize: 13 }}>
                Graph assessment date{" "}
                <input
                  type="date"
                  value={asOf}
                  onChange={(event) => event.target.value && setAsOf(event.target.value)}
                />
              </label>
              <AssessmentScreen nav={nav} target={target} asOf={asOf} />
            </div>
          )}
          {view === "evidence-detail" && evidence && <EvidenceDetailScreen nav={nav} evidence={evidence} asOf={asOf} />}
          {view === "organisation" && <OrganisationScreen />}
          {view === "sources" && <SourcesScreen />}
          {view === "settings" && <SettingsScreen user={user} onUser={setUser} />}
          {view === "components" && <ComponentsScreen />}
        </div>
      </div>
    </div>
  );
}
