"""LLM adapters. One function per provider, all returning the model's raw JSON text.

Config (env vars / Streamlit secrets):
  LLM_PROVIDER      anthropic | openai | gemini | openrouter | mock   (default: mock, needs no key)
  LLM_MODEL         overrides the per-provider default below
  GEMINI_USE_VERTEX_AI  true  -> Vertex AI: express mode with GOOGLE_API_KEY, or GOOGLE_CLOUD_PROJECT +
                                 GOOGLE_CLOUD_LOCATION with Application Default Credentials
                        false -> Google AI Studio with GOOGLE_API_KEY (or GEMINI_API_KEY)
"""
import os
import re

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5-mini",
    "gemini": "gemini-3.8-flash",
    "openrouter": "anthropic/claude-sonnet-5",
    "mock": "keyword-heuristic-v1",
}


def config():
    provider = os.environ.get("LLM_PROVIDER", "mock").strip().lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"LLM_PROVIDER must be one of {', '.join(DEFAULT_MODELS)}; got {provider!r}")
    return provider, os.environ.get("LLM_MODEL", "").strip() or DEFAULT_MODELS[provider]


def _flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def complete_json(system, prompt, schema, provider, model):
    if provider == "anthropic":
        import anthropic
        resp = anthropic.Anthropic().messages.create(
            model=model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("model refused the request")
        return next(b.text for b in resp.content if b.type == "text")

    if provider in ("openai", "openrouter"):
        from openai import OpenAI
        client = (OpenAI(api_key=os.environ.get("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1")
                  if provider == "openrouter" else OpenAI())
        # OpenAI enforces the schema (strict structured output); OpenRouter models vary, so plain JSON mode there.
        fmt = ({"type": "json_object"} if provider == "openrouter" else
               {"type": "json_schema", "json_schema": {"name": "scorecard", "schema": schema, "strict": True}})
        resp = client.chat.completions.create(
            model=model, response_format=fmt,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content

    if provider == "gemini":
        from google import genai
        from google.genai import types
        key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not _flag("GEMINI_USE_VERTEX_AI"):
            client = genai.Client(api_key=key)
        elif os.environ.get("GOOGLE_CLOUD_PROJECT"):
            client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                                  location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"))
        else:  # Vertex AI express mode: API key, no project
            client = genai.Client(vertexai=True, api_key=key)
        resp = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system, response_mime_type="application/json", response_json_schema=schema,
                temperature=0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)),  # no tools here
        )
        return resp.text

    raise ValueError(f"unsupported provider {provider!r}")


STOPWORDS = {"with", "that", "from", "this", "their", "about", "which"}


def mock_evaluate(text, criteria, supplier_name):
    """Keyless, deterministic stand-in for the LLM: scores each criterion by how many lines mention its keywords.
    ponytail: keyword counting, not judgment; use a real provider for meaningful scores."""
    # skip short lines and numbered section headings so evidence is real content; remember each line's page
    lines, page = [], 1
    for raw in text.splitlines():
        l = raw.strip()
        if m := re.fullmatch(r"\[Page (\d+)\]", l):
            page = int(m.group(1))
        elif len(l) > 30 and not re.match(r"\d+\. [A-Z]", l):
            lines.append((page, l))
    results = []
    for c in criteria:
        words = set(re.findall(r"[a-z]{4,}", (c["name"] + " " + c["description"]).lower())) - STOPWORDS
        stems = sorted({w[:5] for w in words})
        pattern = re.compile(r"\b(" + "|".join(map(re.escape, stems)) + ")", re.I)  # word starts only
        hits = [(p, l) for p, l in lines if pattern.search(l)]
        mx = c["max_score"]
        score = round(mx * (0.2 + 0.8 * min(len(hits), 12) / 12))
        best = max(hits, key=lambda h: (len(set(m.lower() for m in pattern.findall(h[1]))), -hits.index(h)),
                   default=None)
        results.append({
            "criterion_id": c["criterion_id"], "score": score, "max_score": mx,
            "justification": f"[mock] {len(hits)} passage(s) mention {', '.join(stems)}.",
            "evidence": f"[Page {best[0]}] {best[1][:240]}" if best else "",
        })
    return {"supplier_name": supplier_name, "criteria": results,
            "risks": ["[mock] Heuristic scoring only; configure LLM_PROVIDER for real evaluation."],
            "overall_summary": f"[mock] Keyword-based evaluation of {supplier_name}."}
