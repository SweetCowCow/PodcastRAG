"""集中放置 service 層共用的 typed exceptions。

不繼承共同 base class（依現有 services 慣例，譬如
`ZSendError(Exception)` / `StorageError(Exception)`）。
"""


class RemoteAudioPathError(Exception):
    """`_transcribe_sync` 收到的 audio_path 不是本地檔（譬如 R2 presigned URL
    或檔案不存在）。worker 層應 catch 並重新下載到 temp 檔再 retry。"""


class OversizedAudioError(Exception):
    """音檔（整檔或單個 chunk）超過 OpenAI Whisper 的 25 MiB hard limit。
    直接 raise 防 silent 413 燒 retry budget。"""


class InvalidProviderConfigError(Exception):
    """ai_steps / provider 配置缺欄位或型別錯（譬如 base_url 是空字串）。
    視為永久錯（task-failure-monitoring-and-circuit-breaker）— retry 沒意義，
    要 admin 進去改設定。"""


class PromptTooLongError(Exception):
    """送進 LLM 的 prompt token 數超過 model context window。永久錯：
    再試也不會通過，要先做 chunking / 截斷 / 降模型。"""


# task-failure-monitoring-and-circuit-breaker provider fallback exceptions —
# 用於 aihub → openai direct fallback 流程的訊號 exception。
class ContentPolicyViolationError(Exception):
    """aihub (Azure OpenAI) 回 400 + 內容過濾器擋下 → 觸發 fallback。"""


class BudgetExceededError(Exception):
    """aihub 回 budget_exceeded → 觸發 fallback（OpenAI direct 沒這個 budget）。"""


class InsufficientQuotaError(Exception):
    """aihub 回 insufficient_quota → 觸發 fallback。"""
