from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    frontend_origin: str
    app_env: str = "development"
    app_debug: bool = False

    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    max_concurrent_transcriptions: int = 1

    # transcription_provider / openai_api_key / zeabur_api_key remain readable
    # at runtime ONLY for the alembic Rev A migration that imports legacy data
    # into the api_keys + ai_steps tables. Once Rev A has run, the application
    # services read everything via services.ai_step_resolver instead.
    transcription_provider: str = "openai"
    openai_api_key: str | None = None
    zeabur_api_key: str | None = None
    openai_whisper_chunk_size_mb: int = 24
    openai_whisper_chunk_overlap_seconds: int = 0
    faster_whisper_model_size: str = "base"
    faster_whisper_compute_type: str = "int8"
    faster_whisper_device: str = "cpu"
    faster_whisper_model_dir: str = "/models/faster-whisper"

    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    r2_endpoint: str | None = None

    # Off-site DB backup bucket (separate from audio bucket above to keep token
    # blast radius + lifecycle policies isolated). All optional so env-not-
    # configured local dev still boots.
    r2_backup_endpoint_url: str | None = None
    r2_backup_access_key_id: str | None = None
    r2_backup_secret_access_key: str | None = None
    r2_backup_bucket: str | None = None
    # Comma-separated age public keys (admin recipient + GHA recipient).
    backup_age_public_key: str | None = None

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    session_secret: str | None = None
    admin_emails: str = ""
    session_ttl_days: int = 14

    e2e_login_token: str | None = None

    # Cron-tick stale-summary recovery: rows whose ai_summary_status='running'
    # for longer than this many seconds get reset to pending and re-enqueued.
    # 600s = 10 min — safely longer than the 30-90s a normal map-reduce takes.
    summary_stale_threshold_seconds: int = 600

    # Freemium onboarding (env-overridable):
    # Default quota assigned to new users on first Google SSO login. Existing
    # users keep their original quota_initial when this changes.
    default_user_quota: int = 30
    # Per-IP daily ceiling for the public segment-search endpoint. Anonymous
    # callers exceeding this limit get 429 ip_rate_limited.
    ip_search_rate_limit_per_day: int = 20
    # disabled-user-appeal-flow: gate the POST /auth/appeal endpoint + the
    # `appeal_enabled` flag in the 403 ACCOUNT_DISABLED response. Default True;
    # set ACCOUNT_APPEAL_ENABLED=false to kill the appeal CTA platform-wide.
    account_appeal_enabled: bool = True
    # Per-IP daily ceiling for POST /auth/appeal. Counts every attempt
    # (including silent-drop ones) so attackers cannot bypass by probing
    # non-disabled emails.
    appeal_ip_rate_limit_per_day: int = 5

    # ZSend email integration (used by the quota-digest beat task). All three
    # are optional — when zsend_api_key is unset, the digest task no-ops with
    # a log entry instead of erroring.
    zsend_api_key: str | None = None
    zsend_from_email: str | None = None
    zsend_admin_to_email: str | None = None  # comma-separated for multiple recipients

    # Multi-provider usage monitoring (multi-provider-usage-monitoring change).
    # - aihub_usage_key / openai_org_admin_key: provider auth tokens. When unset
    #   the respective adapter logs a warning and returns [] (fail-open).
    # - provider_budget_usd_monthly_*: per-provider monthly budgets in USD.
    #   v1 hardcoded defaults; tuneable via env. v2 will add admin UI editor.
    openai_org_admin_key: str | None = None
    aihub_usage_key: str | None = None  # deprecated: 留作向前相容，新 adapter 改讀 zeabur_api_token
    # AI Hub usage 改走 Zeabur 官方 GraphQL（aihub-graphql-adapter-migration）。
    # 從 ~/.config/zeabur/cli.yaml 取得 token；未設則 adapter log warning + 回 []。
    zeabur_api_token: str | None = None
    provider_budget_usd_monthly_aihub: float = 80.0
    provider_budget_usd_monthly_openai: float = 30.0

    # Agentic chat (Phase 2 default-on, enable-agentic-chat-default-on change).
    # Flag 共存 roll-out：default true 走 chat_agent.agent.run_agent；顯式
    # `ENABLE_AGENTIC_CHAT=false` 仍可退回 rule-based pipeline（30 天 kill-switch）。
    enable_agentic_chat: bool = True
    # hyde-retrieval-landing: flag-gated HyDE query rewrite on the chunk
    # retrieve layer (semantic vector only; routing + BM25 lexical unchanged).
    # Default off — flipping to True is a separate decision gated on expanded
    # A/B evidence. `ENABLE_HYDE_RETRIEVAL=true` opts in without code change.
    enable_hyde_retrieval: bool = False
    # b23-dataset-and-retrieval-rca-fix: guest-index dispatch for
    # find_episodes_by_topic (triggers when ≥2 tokens match known guest
    # names). Set ENABLE_GUEST_DISPATCH=false to bypass without redeploy.
    enable_guest_dispatch: bool = True
    # topic-prefilter-transcript-aware: include transcript_chunks tsvector hits as
    # a candidate source in find_episodes_by_topic / find_episodes_by_recency, so
    # narrative episodes whose answer is buried in the transcript (title/desc
    # silent) become candidates. Guarded by a ≥2-discriminating-token gate +
    # ts_rank cap (see transcript_prefilter_cap). Default on; set
    # ENABLE_TRANSCRIPT_TOPIC_PREFILTER=false to revert to title+description only.
    enable_transcript_topic_prefilter: bool = True
    # Max episodes the transcript-chunk source may contribute, ranked by best
    # transcript-chunk ts_rank. Caps non-discriminative over-selection (a single
    # common token like a host name matches ~most transcripts, so this cap — not
    # the tsquery — is the real shortlist filter). Calibrated to 12 via prod DB
    # probe 2026-06-06: existing topic "高雄美食" GT (EP85) ranks 4; b23 EP107
    # ranks 3 on an action-rich topic / 10 on the "Leo"-only token — 12 gives
    # headroom for the latter. Entity-only topics ("迪拉 Leo王") rank EP107 ~27,
    # which no sane cap rescues; that case relies on the LLM extracting action
    # tokens (verified end-to-end by the prod chat smoke).
    transcript_prefilter_cap: int = 12
    # b22-cross-episode-topic-routing: deterministic first-turn tool_choice nudge
    # that forces `search_with_topic_prefilter` when the chat agent receives a
    # cross-episode topical / narrative question (high-precision detector in
    # chat_agent/routing.py). Without it gpt-4o ignores the ToolSpec hint and
    # picks search_across_episodes, leaving the transcript-aware candidate
    # source dormant. Default on (bug fix); set ENABLE_TOPIC_ROUTING_NUDGE=false
    # to revert to pure tool_choice="auto" without a code change.
    enable_topic_routing_nudge: bool = True
    agentic_chat_max_iterations: int = 10
    agentic_chat_l0_k_turns: int = 3
    agentic_chat_l1_ttl_seconds: int = 7200
    agentic_chat_focused_idle_seconds: int = 600
    agentic_chat_enumeration_ttl_seconds: int = 600
    # agent-token-budget-and-tool-truncate: per-tool LLM-facing truncate cap
    # (~2K tokens). result_full stays untouched for admin debug_trace.
    agentic_tool_result_max_chars: int = 8000
    # Per-round token budget (gpt-4o context = 128K; 100K leaves 28K headroom
    # for response + functions schema). When estimated message tokens exceed
    # this, the loop drops oldest tool messages; if still over, finalises
    # with the user-facing truncated answer + agent_truncated=True.
    agentic_chat_messages_max_tokens: int = 100000

    @field_validator("e2e_login_token")
    @classmethod
    def _validate_e2e_login_token(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if len(v) < 32:
            raise ValueError("E2E_LOGIN_TOKEN must be at least 32 chars")
        return v

    # Voyage AI rerank key — used by `_search_with_topic_prefilter` via
    # rag_rerank.voyage_rerank. None disables the rerank stage (fail-open).
    voyage_api_key: str | None = None

    # Langfuse Cloud (Free tier) — eval-framework-upgrade 2026-05-29.
    # Span-level trace observability for chat agent eval runs. All four
    # fields optional: missing keys disable trace upload (SDK no-ops),
    # disabled flag short-circuits the @observe decorator path.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    eval_tracing_enabled: bool = False
    # Independent toggle for per-op timing probe inside trace_span — used by
    # langfuse-sdk-overhead-rca to attribute +3.4s 4.4 overhead among four
    # suspect Langfuse SDK calls. Off by default; turned on only during
    # measurement windows.
    eval_tracing_timing_probe: bool = False

    # r4-rag-result-cache: service-layer retrieval / embedding cache.
    # `rag_cache_enabled` is the master kill-switch for the exact-match cache
    # (embedding + retrieve_hybrid + keyword). Flip to False to bypass the
    # cache entirely without redeploying code paths. TTL is the fallback
    # expiry so entries cannot accumulate forever when corpus / config
    # versions never change (default 7 days).
    rag_cache_enabled: bool = True
    rag_cache_ttl_seconds: int = 604800
    # P2 semantic cache machinery — disabled by default. Flipping on requires
    # a labelled measurement showing false-hit rate ≤5% with net hit-rate gain
    # (enable gate documented in the change design; depends on EQ5 golden set).
    enable_semantic_cache: bool = False
    semantic_cache_threshold: float = 0.95

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # `extra="ignore"` is critical security hygiene: pydantic's default
        # `forbid` mode raises ValidationError that includes the offending env
        # value verbatim — leaking secrets to stderr / logs when a new env var
        # is added without a corresponding Settings field. (2026-05-27: real
        # incident — VOYAGE_API_KEY hit this path before this fix landed.)
        extra="ignore",
    )

    @property
    def frontend_origin_list(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def provider_budget_usd_monthly(self) -> dict[str, float]:
        """Per-provider monthly budget in USD. Returned as a dict so the
        usage-alert task and admin REST endpoint can iterate generically."""
        return {
            "aihub": self.provider_budget_usd_monthly_aihub,
            "openai": self.provider_budget_usd_monthly_openai,
        }

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


settings = Settings()
