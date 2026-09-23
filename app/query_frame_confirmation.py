"""Experimental confirmation component, not promoted into the employee page."""

import json

import streamlit as st

from decidr.query_frames import Interpretation, QueryFrame, validate_interpretation


def render_query_frames(interpretation: Interpretation, context: tuple[str, ...] = ()) -> list[QueryFrame]:
    confirmed = []
    atomic = interpretation.atomic_frames()
    for index, frame in enumerate(atomic):
        with st.container(border=True):
            st.subheader(f"Item {index + 1}: {frame.requested_fields[0].replace('_', ' ')}")
            st.write(frame.original_question)
            st.write(f"Known actor: {frame.known_actor or 'To be retrieved / not supplied'}")
            st.write(
                f"Action: {frame.business_action or 'Needs clarification'} "
                f"{frame.business_object or ''}"
            )
            st.write(f"Process: {frame.process or 'Needs clarification'}")
            st.caption("The requested value will be bound to retrieved evidence after confirmation.")
            with st.form(f"query_frame_{index}"):
                raw = st.text_area("Structured query frame (editable)", frame.model_dump_json(indent=2))
                confirm = st.form_submit_button(f"Confirm item {index + 1}")
            if confirm:
                try:
                    edited = QueryFrame.model_validate_json(raw)
                    frames = [f.model_dump() for f in atomic]
                    frames[index] = edited.model_dump()
                    validate_interpretation(json.dumps({
                        "original_question": interpretation.original_question, "frames": frames,
                    }), interpretation.original_question, context)
                    if edited.needs_clarification:
                        raise ValueError("Resolve the missing material input before confirmation")
                    confirmed.append(edited)
                except ValueError as error:
                    st.error(str(error))
    return confirmed
