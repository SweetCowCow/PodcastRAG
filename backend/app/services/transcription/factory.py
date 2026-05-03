from app.services.ai_step_resolver import (
    AiStepNotConfiguredError,
    StepConfig,
)
from app.services.transcription.base import TranscriptionProvider

SUPPORTED_PROVIDERS = ("openai", "faster-whisper")


def get_provider(step_config: StepConfig) -> TranscriptionProvider:
    """Build a transcription provider instance from a resolved StepConfig.

    The provider type is keyed off `extra_config.provider` (set by admin via
    AiStepsTab; migration default is whatever TRANSCRIPTION_PROVIDER env was
    when Rev A ran).
    """
    provider_name = (step_config.extra_config or {}).get("provider")
    if not provider_name:
        raise AiStepNotConfiguredError(
            "ai_steps.transcription extra_config.provider is missing — "
            "set it in admin (openai or faster-whisper)"
        )
    name = str(provider_name).lower()
    if name == "openai":
        from app.services.transcription.openai_provider import OpenAIWhisperProvider

        return OpenAIWhisperProvider(step_config)
    if name == "faster-whisper":
        from app.services.transcription.faster_whisper_provider import (
            FasterWhisperProvider,
        )

        return FasterWhisperProvider(step_config)
    raise AiStepNotConfiguredError(
        f"unknown transcription provider '{provider_name}'; "
        f"supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )
