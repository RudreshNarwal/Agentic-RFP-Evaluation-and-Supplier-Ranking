"""Agentic RFP Evaluation & Supplier Ranking - Streamlit UI. Built by Rudresh."""
import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from rfp import db, llm
from rfp.document_tool import extract_metadata, extract_text
from rfp.orchestrator import FORMULAS, check_inputs, redact, run_batch
from rfp.ranking import TIE_BREAK_ORDER

st.set_page_config(page_title="Agentic RFP Evaluation", page_icon="📑", layout="wide")


@st.cache_resource
def _init():
    llm.load_env_file()  # local .env (gitignored); real env vars win
    # Streamlit secrets (local .streamlit/secrets.toml or Community Cloud) -> env vars read by rfp.llm
    try:
        for k, v in st.secrets.items():
            if not isinstance(v, dict):
                os.environ.setdefault(k, str(v))
    except Exception:  # no secrets file: plain env vars are used
        pass


@st.cache_data(show_spinner=False)
def _prefill(fname, data):
    """Supplier name, submission date and rating (1-10) stated in the PDF, else sensible defaults."""
    try:
        meta = extract_metadata(extract_text(data)[0])
    except ValueError:  # unreadable file: the orchestrator reports it properly
        meta = {}
    name = meta.get("supplier_name") or Path(fname).stem.replace("_", " ").title()
    rating = meta.get("experience_rating")
    rating = min(10, max(1, round(rating))) if rating is not None else 5
    try:
        submitted = date.fromisoformat(meta.get("submission_date") or "").isoformat()
    except ValueError:  # not stated, or not a real date
        submitted = str(date.today())
    return name, submitted, rating


PROVIDER_LABELS = {"gemini": "Google Gemini", "anthropic": "Anthropic Claude", "openai": "OpenAI",
                   "openrouter": "OpenRouter", "mock": "Mock (offline, no key)"}
KEY_LABELS = {"gemini": "Google API key", "anthropic": "Anthropic API key", "openai": "OpenAI API key",
              "openrouter": "OpenRouter API key"}
PING_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def _llm_settings():
    """Sidebar provider / model / endpoint / key. Defaults come from the server config; a key typed here is kept only
    in this browser session and passed to each call - never written to env, SQLite, the run JSON or logs."""
    try:
        env_provider, env_model = llm.config()
    except ValueError as e:
        st.warning(f"{e} Pick a provider below.")
        env_provider, env_model = "mock", llm.DEFAULT_MODELS["mock"]
    names = list(llm.DEFAULT_MODELS)
    provider = st.selectbox("Provider", names, index=names.index(env_provider), format_func=PROVIDER_LABELS.get,
                            key="llm_provider")
    model = st.text_input("Model", value=env_model if provider == env_provider else llm.DEFAULT_MODELS[provider],
                          key=f"llm_model_{provider}").strip() or llm.DEFAULT_MODELS[provider]
    creds, ready = {}, True
    if provider == "mock":
        st.info("Mock mode: keyword heuristic for offline tests; scores are not meaningful.")
        return provider, model, creds, ready

    if provider == "gemini":
        endpoint = st.radio("Google endpoint", ["AI Studio", "Vertex AI"], index=1 if llm.use_vertex() else 0,
                            horizontal=True, key="llm_endpoint",
                            help="AI Studio: key from aistudio.google.com. Vertex AI: a key allowed on the Vertex AI "
                                 "API (express mode). If Vertex rejects the key, AI Studio is used and a warning shown.")
        creds["vertex"] = endpoint == "Vertex AI"
    has_server_key = bool(llm.server_key(provider))
    key = st.text_input(KEY_LABELS[provider], type="password", key=f"llm_key_{provider}",
                        placeholder="Using the key configured on the server" if has_server_key else "Paste your API key",
                        help="Used only in this browser session for your runs. Never saved, logged or shared.").strip()
    if key:
        creds["api_key"] = key
    elif not has_server_key:
        st.warning(f"Add a {KEY_LABELS[provider]} to evaluate.")
        ready = False

    if st.button("Test connection", disabled=not ready, width="stretch"):
        try:
            llm.complete_json("Reply with JSON only.", 'Return {"ok": true}.', PING_SCHEMA, provider, model, **creds)
            backend, note = llm.gemini_backend(**creds) if provider == "gemini" else (None, None)
            st.success(f"Connected: {provider} · {model}" + (f" via {backend}" if backend else ""))
            if note:
                st.warning(note)
        except Exception as e:
            st.error(f"Connection failed: {type(e).__name__}: {redact(str(e), creds)[:300]}")
    return provider, model, creds, ready


def _show_llm(slot, provider, model, creds):
    backend, note = llm.gemini_backend(**creds) if provider == "gemini" else (None, None)
    with slot.container():
        st.markdown(f"**LLM:** `{provider}` · `{model}`" + (f"  \n**Endpoint:** {backend}" if backend else ""))
        if note:
            st.warning(note)


def _open_past_run():
    if st.session_state.past_run != "—":
        st.session_state.run = db.load_run(st.session_state.past_run)


_init()
db.init_db()  # every rerun: idempotent and cheap, and recreates tables if the DB file was reset

# ---------- sidebar ----------
with st.sidebar:
    st.title("📑 Agentic RFP Evaluation")
    st.caption("Supplier proposals → LLM scorecards → deterministic peer ranking")
    with st.expander("⚙️ LLM settings", expanded=True):
        provider, model, llm_creds, llm_ready = _llm_settings()
    llm_slot = st.empty()  # redrawn after a run: the Gemini endpoint is only known once Vertex has been tried
    _show_llm(llm_slot, provider, model, llm_creds)

    runs = [r for r in db.list_runs() if r["status"] == "completed"]
    if runs:
        st.selectbox("Open a past run", ["—"] + [r["rfp_run_id"] for r in runs], key="past_run",
                     on_change=_open_past_run)
    st.divider()
    st.caption("Built by **Rudresh** · Streamlit + SQLite + any JSON-capable LLM")

run = st.session_state.get("run")
tabs = st.tabs(["① Criteria", "② Suppliers & Evaluate", "③ Leaderboard", "④ Scorecards", "⑤ Run details"])

# ---------- 1. criteria ----------
with tabs[0]:
    active = db.get_criteria()
    total = sum(c["weight"] for c in active)
    st.subheader("Active evaluation criteria")
    c1, c2 = st.columns(2)
    c1.metric("Active criteria", len(active))
    c2.metric("Total weight", f"{total:g}%", delta="OK" if abs(total - 100) < 1e-6 else "must be 100%",
              delta_color="normal" if abs(total - 100) < 1e-6 else "inverse", delta_arrow="off")
    st.dataframe(pd.DataFrame(active)[["criterion_id", "name", "description", "weight", "max_score"]] if active else
                 pd.DataFrame(), hide_index=True, width="stretch",
                 column_config={"weight": st.column_config.NumberColumn("weight (%)", format="%g"),
                                "max_score": st.column_config.NumberColumn(format="%g")})

    with st.expander("Edit criteria (activate / deactivate / change weights)"):
        edited = st.data_editor(
            pd.DataFrame(db.get_criteria(active_only=False)), hide_index=True, width="stretch", num_rows="fixed",
            disabled=["criterion_id"], key="criteria_editor",
            column_config={"is_active": st.column_config.CheckboxColumn("active"),
                           "weight": st.column_config.NumberColumn("weight (%)", min_value=0, max_value=100),
                           "max_score": st.column_config.NumberColumn(min_value=1)})
        new_total = edited.loc[edited["is_active"].astype(bool), "weight"].sum()
        st.caption(f"Active weight total after edit: **{new_total:g}%**")
        if st.button("Save criteria"):
            if abs(new_total - 100) > 1e-6:
                st.error(f"Active weights total {new_total:g}%. They must total exactly 100% - not saved.")
            else:
                db.save_criteria(edited.to_dict("records"))
                st.success("Criteria saved. New runs will use them.")
                st.rerun()

# ---------- 2. supplier input ----------
with tabs[1]:
    st.subheader("Supplier proposals")
    uploads = st.file_uploader("Upload supplier RFP responses (PDF)", type=["pdf"], accept_multiple_files=True)
    files = [(f.name, f.getvalue()) for f in uploads or []]

    submissions = []
    if files:
        st.markdown("**Supplier metadata**")
        h = st.columns([3, 3, 2, 2])
        for col, label in zip(h, ["File", "Supplier name", "Submission date", "Experience (1-10)"]):
            col.caption(label)
        st.caption("Pre-filled from each PDF where it states them - check and edit before evaluating.")
        for i, (fname, data) in enumerate(files):
            name0, date0, rating0 = _prefill(fname, data)
            c = st.columns([3, 3, 2, 2])
            c[0].markdown(f"`{fname}`  \n{len(data) / 1024:.0f} KB")
            name = c[1].text_input("Supplier name", name0, key=f"name{i}{fname}", label_visibility="collapsed")
            sdate = c[2].date_input("Submission date", date.fromisoformat(date0), key=f"date{i}{fname}",
                                    label_visibility="collapsed")
            rating = c[3].slider("Experience rating", 1, 10, rating0, key=f"rate{i}{fname}", label_visibility="collapsed")
            submissions.append({"supplier_name": name, "submission_date": sdate.isoformat(),
                                "experience_rating": rating, "pdf_bytes": data, "filename": fname})

    errors = check_inputs(submissions, db.get_criteria())
    if not submissions:
        st.info("Upload two or more supplier PDFs to compare.")
    else:
        for e in errors:
            st.error(e)
    if len(submissions) == 1:
        st.warning("Only one supplier: peer benchmarks will simply compare it with itself.")
    if not llm_ready:
        st.error("Add an API key in the sidebar (⚙️ LLM settings) before evaluating.")

    if st.button("🚀 Evaluate suppliers", type="primary", disabled=bool(errors) or not llm_ready):
        with st.status(f"Running agentic workflow with {provider}/{model}…", expanded=True) as status:
            try:
                run = run_batch(submissions, provider=provider, model=model, on_progress=status.write,
                                credentials=llm_creds)
                _show_llm(llm_slot, provider, model, llm_creds)
                st.session_state.run = run
                status.update(label=f"Completed {run['rfp_run_id']} · {len(run['warnings'])} warning(s)",
                              state="complete", expanded=False)
            except Exception as e:
                status.update(label="Run failed", state="error")
                st.error(f"{type(e).__name__}: {redact(str(e), llm_creds)}")
        if st.session_state.get("run"):
            st.success("Done - open the **Leaderboard**, **Scorecards** and **Run details** tabs.")


def _md(text):
    """LLM/PDF text into markdown: escape $ so prices like '$410,000 ... $60,000' don't render as LaTeX."""
    return str(text).replace("$", "\\$")


def _badge(verified):
    return {True: "✅ verified", False: "⚠️ not found in PDF"}.get(verified, "—")


def _verified(s):
    return f"{sum(bool(c.get('evidence_verified')) for c in s['criteria'])}/{len(s['criteria'])}"


def _need_run():
    st.info("No run yet. Evaluate suppliers in tab ②, or open a past run from the sidebar.")


# ---------- 3. leaderboard ----------
with tabs[2]:
    if not run:
        _need_run()
    else:
        sup = run["suppliers"]
        st.subheader(f"Leaderboard · {run['rfp_run_id']}")
        top = sup[0]
        m = st.columns(3)
        m[0].metric("🏆 Rank 1", top["supplier_name"])
        m[1].metric("PPI", f"{top['ppi']:.2f}")
        m[2].metric("Absolute score", f"{top['absolute_score']:.2f} / 100")
        board = pd.DataFrame([{
            "Rank": s["final_rank"], "Supplier": s["supplier_name"],
            "": "⚠️" if s.get("evaluation_status") == "failed" else "✅", "Absolute score": s["absolute_score"],
            "PPI": s["ppi"], "Submission date": s["submission_date"], "Experience rating": s["experience_rating"],
            "Evidence ✓": _verified(s), "Warnings": len(s["warnings"]),
            "Why this position": s["tie_break_note"]} for s in sup])
        st.dataframe(board, hide_index=True, width="stretch", column_config={
            "Absolute score": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=100),
            "PPI": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=100)})

        st.markdown("**Criterion comparison** - score (relative % of best) per supplier")
        comp = pd.DataFrame({s["supplier_name"]: {f"{c['name']} ({c['weight']:g}%)":
                             f"{c['score']:g}/{c['max_score']:g} ({c['relative_pct']:.0f}%)" for c in s["criteria"]}
                             for s in sup})
        comp["Benchmark"] = [f"{c['benchmark']:g}" for c in sup[0]["criteria"]]
        st.dataframe(comp, width="stretch")
        st.bar_chart(board.set_index("Supplier")[["PPI", "Absolute score"]], stack=False, horizontal=True, sort=False)

# ---------- 4. scorecards ----------
with tabs[3]:
    if not run:
        _need_run()
    else:
        names = [s["supplier_name"] for s in run["suppliers"]]
        s = run["suppliers"][names.index(st.selectbox("Supplier", names))]
        m = st.columns(4)
        m[0].metric("Rank", s["final_rank"])
        m[1].metric("Absolute score", f"{s['absolute_score']:.2f}")
        m[2].metric("PPI", f"{s['ppi']:.2f}")
        m[3].metric("Warnings", len(s["warnings"]))
        if s.get("evaluation_status") == "failed":
            st.error("This supplier could not be evaluated (see warnings); it is scored 0 on every criterion.")
        if s.get("self_correction"):
            sc = s["self_correction"]
            st.info(f"🔁 Self-correction: the validator found {len(sc['issues_before'])} issue(s); the Evaluation Agent "
                    f"re-answered with {len(sc['issues_after'])} issue(s) - "
                    f"{'corrected answer used' if sc['accepted'] else 'first answer kept'}.")
        if s["overall_summary"]:
            st.markdown(f"> {_md(s['overall_summary'])}")
        st.dataframe(pd.DataFrame([{
            "Criterion": c["name"], "Weight %": c["weight"], "Score": f"{c['score']:g} / {c['max_score']:g}",
            "Weighted points": c["weighted_points"], "Benchmark": c["benchmark"], "Gap": c["gap"],
            "Relative %": c["relative_pct"], "Evidence": _badge(c.get("evidence_verified"))} for c in s["criteria"]]),
            hide_index=True, width="stretch",
            column_config={"Relative %": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100)})
        st.markdown("**Evidence & justification**")
        for c in s["criteria"]:
            with st.expander(f"{_badge(c.get('evidence_verified'))} {c['name']} - {c['score']:g}/{c['max_score']:g}  "
                             f"(gap {c['gap']:+g} vs benchmark {c['benchmark']:g})"):
                st.markdown(f"**Justification:** {_md(c['justification']) or '—'}")
                st.markdown("**Evidence:**\n\n" + (f"> {_md(c['evidence'])}" if c["evidence"] else "_No evidence quoted._"))
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Risks identified**")
            for r in s["risks"] or ["None reported."]:
                st.markdown(f"- {_md(r)}")
        with c2:
            st.markdown("**Validation warnings**")
            for w in s["warnings"] or ["None."]:
                st.markdown(f"- {_md(w)}")

# ---------- 5. run details ----------
with tabs[4]:
    if not run:
        _need_run()
    else:
        st.subheader(f"RFP_RUN_ID: `{run['rfp_run_id']}`")
        st.markdown(f"**Status:** {run['status']} · **Created:** {run['created_at'].replace('T', ' ')} · "
                    f"**LLM:** `{run['llm']['provider']}` / `{run['llm']['model']}` · **Suppliers:** {len(run['suppliers'])}")
        st.download_button("⬇️ Download complete result (JSON)", json.dumps(run, indent=2),
                           file_name=f"{run['rfp_run_id']}.json", mime="application/json", type="primary")

        st.markdown("**Warnings**")
        if run["warnings"]:
            for w in run["warnings"]:
                st.warning(_md(w))
        else:
            st.success("No validation warnings - every LLM scorecard was complete and in range.")

        st.markdown("**Tie-break explanation** - order: " + " → ".join(TIE_BREAK_ORDER))
        st.dataframe(pd.DataFrame([{"Rank": s["final_rank"], "Supplier": s["supplier_name"], "PPI": s["ppi"],
                                    "Submission date": s["submission_date"], "Experience": s["experience_rating"],
                                    "Explanation": s["tie_break_note"]} for s in run["suppliers"]]),
                     hide_index=True, width="stretch", column_config={"PPI": st.column_config.NumberColumn(format="%.4f")})
        st.markdown("**Orchestrator step log** - every tool call, in order")
        st.dataframe(pd.DataFrame(run["steps"]), hide_index=True, width="stretch")
        st.markdown("**Formulas (deterministic Python)**")
        st.dataframe(pd.DataFrame(FORMULAS.items(), columns=["Metric", "Formula"]), hide_index=True, width="stretch")
        with st.expander("Raw JSON"):
            st.json(run, expanded=False)
