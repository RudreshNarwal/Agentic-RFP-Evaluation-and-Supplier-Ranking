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
    monkeypatch.setattr(llm, "_vertex_blocked", set())
    assert llm.gemini_backend() == ("vertex-ai", None)
    assert llm.complete_json("s", "p", {}, "gemini", "m") == '{"ok": true}'
    assert llm.complete_json("s", "p", {}, "gemini", "m") == '{"ok": true}'
    assert calls == ["vertex", "ai-studio", "ai-studio"]  # Vertex tried once, then skipped
    backend, note = llm.gemini_backend()
    assert backend == "ai-studio" and "rejected the API key" in note


def test_call_level_key_is_used_without_touching_env_and_blocking_is_per_key(monkeypatch):
    seen = []

    class FakeClient:
        def __init__(self, vertexai=False, api_key=None, **kw):
            self.models, self.vertex, self.key = self, vertexai, api_key

        def generate_content(self, **kw):
            seen.append(("vertex" if self.vertex else "ai-studio", self.key))
            if self.vertex and self.key == "ui-key":
                raise errors.ClientError(403, {"error": {"code": 403, "message": "blocked", "status": "PERMISSION_DENIED"}})
            return type("R", (), {"text": "{}"})()

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.setenv("GOOGLE_API_KEY", "server-key")
    monkeypatch.setenv("GEMINI_USE_VERTEX_AI", "false")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setattr(llm, "_vertex_blocked", set())

    llm.complete_json("s", "p", {}, "gemini", "m", api_key="ui-key", vertex=True)  # UI key, Vertex chosen in the UI
    llm.complete_json("s", "p", {}, "gemini", "m", vertex=True)                    # server key on Vertex still tried
    llm.complete_json("s", "p", {}, "gemini", "m")                                 # server default: AI Studio
    assert seen == [("vertex", "ui-key"), ("ai-studio", "ui-key"), ("vertex", "server-key"), ("ai-studio", "server-key")]
    assert os.environ["GOOGLE_API_KEY"] == "server-key"  # the UI key never leaked into the process env
    assert llm.gemini_backend(api_key="ui-key", vertex=True)[0] == "ai-studio"
    assert llm.gemini_backend(vertex=True) == ("vertex-ai", None)
