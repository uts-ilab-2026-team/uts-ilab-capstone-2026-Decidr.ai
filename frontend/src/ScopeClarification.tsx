import { useState } from "react";
import type { ScopeContext } from "./api";

export default function ScopeClarification({ context, onAnswer }: {
  context: ScopeContext; onAnswer: (answer: string | null) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [dismissed, setDismissed] = useState(false);
  if (context.status === "not_requested") return null;
  if (context.status === "scope_supplied") return <section className="ev-card" aria-label="Selected claim scope">
    <h2>Scope you supplied</h2><p>{context.answer}</p>
    <p className="ev-muted">This scope accompanies your original claim. Evidence is still unassessed.</p>
    <button type="button" className="ev-button" onClick={() => onAnswer(null)}>Change scope</button>
  </section>;
  if (dismissed) return <button className="ev-button" onClick={() => setDismissed(false)}>Clarify claim scope</button>;
  return <section className="ev-card" aria-label="Clarify claim scope">
    <h2>{context.question}</h2>
    <p className="ev-muted">The corpus distinguishes these scopes or decision stages. You can clarify the scope or continue inspecting evidence.</p>
    <div className="ev-chips">{context.options.map(option => <button type="button" className="ev-button" key={option} onClick={() => onAnswer(option)}>{option}</button>)}</div>
    <form onSubmit={event => { event.preventDefault(); if (answer.trim()) onAnswer(answer.trim()); }}>
      <label>Another scope or explanation<input value={answer} maxLength={500} onChange={event => setAnswer(event.target.value)} /></label>
      <button type="submit" className="ev-button" disabled={!answer.trim()}>Use this scope</button>
    </form>
    <button type="button" className="ev-button" onClick={() => setDismissed(true)}>Continue without narrowing</button>
    <details><summary>Why this question?</summary>
      {context.basis.map(item => <div key={`${item.evidence_id}:${item.label}`}><p>{item.source_title}</p><blockquote>{item.quotation}</blockquote><p className="ev-muted">{item.evidence_id} · {item.locator}</p></div>)}
      <p className="ev-muted">These passages explain the scope distinction; their current applicability has not been assessed.</p>
    </details>
  </section>;
}
