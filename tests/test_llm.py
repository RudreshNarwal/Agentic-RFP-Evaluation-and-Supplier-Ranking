"""LLM config: .env loading and the Vertex -> AI Studio fallback (no network)."""
import os

from google.genai import errors

from rfp import llm


def test_env_file_loads_but_real_env_wins(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# comment\nLLM_PROVIDER=gemini\nGEMINI_USE_VERTEX_AI="true"  # inline\nTEST_ONLY_KEY=abc\n')
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("GEMINI_USE_VERTEX_AI", raising=False)
    monkeypatch.delenv("TEST_ONLY_KEY", raising=False)
    llm.load_env_file(str(f))
    assert os.environ["LLM_PROVIDER"] == "mock" and os.environ["GEMINI_USE_VERTEX_AI"] == "true"
    assert os.environ.pop("TEST_ONLY_KEY") == "abc"


def test_vertex_403_falls_back_to_ai_studio_and_reports_it(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, vertexai=False, **kw):
            self.models = self
            self.vertex = vertexai

        def generate_content(self, **kw):
            calls.append("vertex" if self.vertex else "ai-studio")
            if self.vertex:
                raise errors.ClientError(403, {"error": {"code": 403, "message": "blocked", "status": "PERMISSION_DENIED"}})
            return type("R", (), {"text": '{"ok": true}'})()

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.setenv("GEMINI_USE_VERTEX_AI", "true")
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setattr(llm, "_vertex_blocked", False)
    assert llm.gemini_backend() == ("vertex-ai", None)
    assert llm.complete_json("s", "p", {}, "gemini", "m") == '{"ok": true}'
    assert llm.complete_json("s", "p", {}, "gemini", "m") == '{"ok": true}'
    assert calls == ["vertex", "ai-studio", "ai-studio"]  # Vertex tried once, then skipped
    backend, note = llm.gemini_backend()
    assert backend == "ai-studio" and "Vertex AI rejected the API key" in note
