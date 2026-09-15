"""Claim registration, atomicity assistance, and lexical retrieval."""

from datetime import date
import json
from time import perf_counter
import uuid

import pandas as pd
import streamlit as st

from decidr.candidate_portfolio import load_candidate_portfolio
from decidr.claims import check_atomicity, split_claim
from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import connect, save_claim, save_retrieval_run
from decidr.hybrid import reciprocal_rank_fusion
from decidr.models import AtomicClaim
from decidr.retrieval import lexical_search
from decidr.semantic import (
    SemanticUnavailableError,
    SentenceTransformerEmbedder,
    semantic_search,
)

st.title("Claims and Lexical Retrieval")


def optional_date(value: str) -> date | None:
    """Parse an optional reviewer-entered ISO date."""
    return date.fromisoformat(value.strip()) if value.strip() else None


def phase_mirror_key(source_id: str, locator: str) -> tuple[str, str]:
    """Identify the same source/location when it appears in multiple corpus phases."""
    canonical_source = source_id.split(":", 1)[-1]
    return canonical_source, locator


candidate_path = PROJ_ROOT / "framework" / "candidate_claim_portfolio.csv"
design_path = PROJ_ROOT / "framework" / "candidate_claim_portfolio_design.csv"
study_config_path = PROJ_ROOT / "configs" / "human_study.json"
if candidate_path.is_file():
    configuration = json.loads(study_config_path.read_text(encoding="utf-8"))
    if configuration["portfolio_status"] == "approved_and_frozen":
        st.subheader("Approved and frozen claim portfolio v1.1-final")
        st.info(
            "These eight claims are frozen study inputs, not adjudicated ground truth. Ordinary "
            "editing is disabled; any change requires an explicit new portfolio version."
        )
    else:
        st.subheader("Corpus-verified candidate portfolio awaiting final human approval")
        st.warning("These corpus-checked proposals are not yet approved or adjudicated ground truth.")
    validated_candidates = load_candidate_portfolio(candidate_path, study_config_path)
    candidates = pd.read_csv(candidate_path, dtype=str, keep_default_na=False)
    st.caption(f"{len(validated_candidates)} rows passed the AtomicClaim schema validation gate.")
    display = candidates[
        [
            "candidate_claim_id",
            "exact_claim_wording",
            "subject",
            "relationship_predicate",
            "target_object",
            "evidence_target",
            "applicable_start_date",
            "applicable_end_date",
            "evaluation_split",
        ]
    ].rename(
        columns={
            "candidate_claim_id": "ID",
            "exact_claim_wording": "Exact claim wording",
            "subject": "Subject",
            "relationship_predicate": "Predicate",
            "target_object": "Target/object",
            "evidence_target": "Evidence target",
            "applicable_start_date": "Applicable start",
            "applicable_end_date": "Applicable end",
            "evaluation_split": "Split",
        }
    )
    st.dataframe(display, use_container_width=True, hide_index=True)
    with st.expander("Full administrative claim metadata"):
        st.dataframe(candidates, use_container_width=True, hide_index=True)
    st.download_button(
        "Download candidate portfolio CSV",
        candidate_path.read_bytes(),
        candidate_path.name,
        "text/csv",
    )
    reviewer_names = list(configuration["reviewers"].values())
    st.caption(
        f"Configured reviewers: {reviewer_names[0]} and {reviewer_names[1]}. "
        "The administrative split is six development and two held-out. Reviewer-facing "
        "workspaces do not expose this allocation."
    )
    if design_path.is_file():
        with st.expander("Portfolio-design record (excluded from blind reviewer packets)"):
            design = pd.read_csv(design_path, dtype=str, keep_default_na=False)
            st.dataframe(design, use_container_width=True, hide_index=True)
            st.download_button(
                "Download portfolio-design CSV",
                design_path.read_bytes(),
                design_path.name,
                "text/csv",
            )


st.subheader("Approved claim register")
with st.form("claim"):
    claim_id = st.text_input("Claim ID")
    claim_text = st.text_area("Original claim wording")
    subject = st.text_input("Subject")
    predicate = st.text_input("Relationship / predicate")
    object_value = st.text_input("Target / object")
    process = st.text_input("Process")
    scope = st.text_input("Scope")
    conditions_text = st.text_area("Conditions (one per line)")
    applicable_start = st.text_input("Applicable start date (YYYY-MM-DD, optional)")
    applicable_end = st.text_input("Applicable end date (YYYY-MM-DD, optional)")
    claim_type = st.text_input("Claim type", value="organisational_knowledge")
    split = st.selectbox("Evaluation split", ["development", "held_out"])
    submitted = st.form_submit_button("Check and save claim")
if submitted:
    atomicity = check_atomicity(claim_text)
    claim = AtomicClaim(
        claim_id=claim_id,
        subject=subject,
        predicate=predicate,
        object=object_value,
        process=process or None,
        scope=scope or None,
        conditions=[line.strip() for line in conditions_text.splitlines() if line.strip()],
        applicable_start_date=optional_date(applicable_start),
        applicable_end_date=optional_date(applicable_end),
        claim_type=claim_type,
        claim_text=claim_text,
        original_claim_text=claim_text,
        atomicity_status=atomicity.status,
        ambiguity_notes=" ".join(atomicity.reasons) or None,
        evaluation_split=split,
    )
    with connect(DATABASE_PATH) as connection:
        save_claim(connection, claim)
    st.success(f"Saved {claim.claim_id}; atomicity status: {atomicity.status}")
    if atomicity.reasons:
        st.warning(" ".join(atomicity.reasons))

with connect(DATABASE_PATH) as connection:
    claim_rows = connection.execute("SELECT payload_json FROM claims ORDER BY claim_id").fetchall()
claims = [AtomicClaim.model_validate(json.loads(row[0])) for row in claim_rows]
editable_claims = [claim for claim in claims if claim.portfolio_status != "approved_and_frozen"]
if claims:
    frozen_count = sum(
        claim.portfolio_status == "approved_and_frozen" for claim in claims
    )
    if frozen_count:
        st.info(
            f"{frozen_count} approved portfolio claims are immutable. Amendments require a new "
            "portfolio version and cannot overwrite these records."
        )
if editable_claims:
    st.subheader("Edit or split an existing claim")
    edit_id = st.selectbox(
        "Claim to edit", [claim.claim_id for claim in editable_claims], key="edit_claim"
    )
    editable = next(claim for claim in editable_claims if claim.claim_id == edit_id)
    with st.form("edit_claim_form"):
        edited_text = st.text_area("Claim wording", value=editable.claim_text)
        edited_scope = st.text_input("Claim scope", value=editable.scope or "")
        edited_conditions = st.text_area(
            "Conditions (one per line)", value="\n".join(editable.conditions)
        )
        edited_start = st.text_input(
            "Applicable start date",
            value=(
                editable.applicable_start_date.isoformat()
                if editable.applicable_start_date
                else ""
            ),
        )
        edited_end = st.text_input(
            "Applicable end date",
            value=(editable.applicable_end_date.isoformat() if editable.applicable_end_date else ""),
        )
        inclusion = st.selectbox(
            "Inclusion status",
            ["included", "excluded"],
            index=0 if editable.inclusion_status == "included" else 1,
        )
        exclusion_reason = st.text_input(
            "Exclusion reason", value=editable.exclusion_reason or ""
        )
        save_edit = st.form_submit_button("Save edits")
    if save_edit:
        atomicity = check_atomicity(edited_text)
        updated = editable.model_copy(
            update={
                "claim_text": edited_text,
                "scope": edited_scope or None,
                "conditions": [line.strip() for line in edited_conditions.splitlines() if line.strip()],
                "applicable_start_date": optional_date(edited_start),
                "applicable_end_date": optional_date(edited_end),
                "atomicity_status": atomicity.status,
                "ambiguity_notes": " ".join(atomicity.reasons) or None,
                "inclusion_status": inclusion,
                "exclusion_reason": exclusion_reason or None,
            }
        )
        updated = AtomicClaim.model_validate(updated.model_dump())
        with connect(DATABASE_PATH) as connection:
            save_claim(connection, updated)
        st.success("Claim edits saved with the original wording retained in the record.")

    with st.form("split_claim_form"):
        components = st.text_area("Compound-claim components (one complete claim per line)")
        save_split = st.form_submit_button("Create preserved child claims")
    if save_split:
        children = split_claim(
            editable, [line.strip() for line in components.splitlines() if line.strip()]
        )
        with connect(DATABASE_PATH) as connection:
            for child in children:
                save_claim(connection, child)
        st.success(f"Created {len(children)} child claims; original wording was preserved.")

if claims:
    st.download_button(
        "Export claim register JSON",
        json.dumps([claim.model_dump(mode="json") for claim in claims], indent=2),
        "claim_register.json",
        "application/json",
    )

    st.subheader("Retrieve evidence")
    selected_id = st.selectbox("Claim to retrieve for", [claim.claim_id for claim in claims])
    selected_claim = next(claim for claim in claims if claim.claim_id == selected_id)
    limit = st.slider("Result limit", 5, 50, 20)
    method = st.selectbox("Retrieval method", ["Lexical", "Semantic", "Hybrid"])
    if st.button("Run retrieval"):
        started = perf_counter()
        model_name = None
        model_version = None
        with connect(DATABASE_PATH) as connection:
            lexical = lexical_search(connection, selected_claim, limit=limit)
            if method == "Lexical":
                results = lexical
            else:
                try:
                    embedder = SentenceTransformerEmbedder()
                    semantic = semantic_search(
                        connection,
                        selected_claim,
                        embedder,
                        limit=limit,
                    )
                    model_name = embedder.name
                    model_version = embedder.version
                except SemanticUnavailableError as error:
                    st.error(str(error))
                    st.stop()
                results = (
                    semantic
                    if method == "Semantic"
                    else reciprocal_rank_fusion(lexical, semantic, limit=limit)
                )
            mirror_counts: dict[tuple[str, str], int] = {}
            for item in results:
                key = phase_mirror_key(item.source_id, item.locator)
                mirror_counts[key] = mirror_counts.get(key, 0) + 1

            phase_mirror_duplicates = sum(
                count - 1 for count in mirror_counts.values() if count > 1
            )

            latency_ms = (perf_counter() - started) * 1000
            run_id = f"RUN-{uuid.uuid4().hex}"
            persisted = []
            for item in results:
                scores = {}
                for name in (
                    "score",
                    "combined_score",
                    "lexical_rank",
                    "semantic_rank",
                    "matched_terms",
                ):
                    if hasattr(item, name):
                        scores[name] = getattr(item, name)
                persisted.append(
                    {
                        "evidence_id": item.evidence_id,
                        "rank": item.rank,
                        "component_scores": scores,
                    }
                )
            save_retrieval_run(
                connection,
                run_id=run_id,
                claim_id=selected_claim.claim_id,
                method=method.casefold(),
                query_text=selected_claim.claim_text,
                configuration={"limit": limit, "rrf_k": 60 if method == "Hybrid" else None},
                latency_ms=latency_ms,
                results=persisted,
                model_name=model_name,
                model_version=model_version,
            )
        st.caption("Retrieval proposes candidates only; reviewers must assess applicability.")
        st.caption(f"Run `{run_id}` persisted in {latency_ms:.1f} ms.")
        if phase_mirror_duplicates:
            st.warning(
                f"{phase_mirror_duplicates} result(s) appear to repeat the same source/location "
                "across corpus phases. They are retained for provenance but should not be treated "
                "as independent corroborating evidence."
            )
        seen_mirror_keys: set[tuple[str, str]] = set()
        for item in results:
            key = phase_mirror_key(item.source_id, item.locator)
            mirror_label = " ⚠ phase mirror" if key in seen_mirror_keys else ""
            seen_mirror_keys.add(key)

            with st.expander(
                f"#{item.rank} {item.source_id} — {item.locator}{mirror_label}"
            ):
                if method == "Lexical":
                    st.write(item.match_explanation)
                    st.code(f"BM25 display score: {item.score:.6f}")
                elif method == "Semantic":
                    st.write(f"Local cosine similarity: {item.score:.6f}")
                    st.caption(f"Model: {item.model_name}, package version: {item.model_version}")
                else:
                    st.write(
                        f"RRF score: {item.combined_score:.6f}; lexical rank: "
                        f"{item.lexical_rank}; semantic rank: {item.semantic_rank}"
                    )
                st.text(item.text)
else:
    st.info("Create a claim to enable retrieval.")
