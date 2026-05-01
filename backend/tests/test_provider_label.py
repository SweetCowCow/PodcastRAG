from app.services.llm_config import infer_provider_label


def test_none_base_url_returns_openai():
    assert infer_provider_label(None) == "OpenAI"


def test_official_openai_returns_openai():
    assert infer_provider_label("https://api.openai.com/v1") == "OpenAI"


def test_zeabur_returns_zeabur_ai_hub():
    assert infer_provider_label("https://aihub-xyz.zeabur.app/v1") == "Zeabur AI Hub"


def test_unknown_provider_falls_back_to_hostname():
    assert infer_provider_label("https://api.together.xyz/v1") == "api.together.xyz"
