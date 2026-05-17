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
