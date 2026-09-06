"""Microsoft Foundry Models 呼び出しの抽象化。

モデル名・API バージョン・API スタイルはすべて設定値で切り替えられます。
ビジネスロジック側は :class:`InsightsGenerator` にのみ依存します。
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from newsproc.config import FoundrySettings
from newsproc.logging_utils import log_info, log_warning
from newsproc.models import INSIGHTS_JSON_SCHEMA, ArticleInsights, NormalizedArticle
from newsproc.prompts import SYSTEM_PROMPT, build_user_prompt

#: 構造化出力のスキーマ名。
SCHEMA_NAME = "article_insights"

#: モデルが対応していないパラメーターを示すエラーメッセージのパターン。
_UNSUPPORTED_PARAM_RE = re.compile(
    r"(unsupported[_ ]parameter|unsupported value|is not supported with this model|"
    r"unrecognized request argument|does not support)",
    re.IGNORECASE,
)

#: リトライ対象とみなす一時的エラーのパターン。
_TRANSIENT_RE = re.compile(r"(429|rate.?limit|timeout|timed out|50[0234]|overload|temporarily)", re.IGNORECASE)


class FoundryError(Exception):
    """Foundry 呼び出しの失敗。"""

    def __init__(self, message: str, *, category: str = "unknown") -> None:
        super().__init__(message)
        self.category = category


@dataclass
class InsightsResult:
    """モデル呼び出しの結果と計測値。"""

    insights: ArticleInsights
    deployment: str
    model_version: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: int = 1
    duration_ms: float = 0.0


class InsightsGenerator(Protocol):
    """記事から日本語の構造化インサイトを生成するインターフェイス。"""

    def generate(self, article: NormalizedArticle, body_text: str | None) -> InsightsResult:  # pragma: no cover
        ...


def _extract_json(text: str) -> dict[str, Any]:
    """モデル出力から JSON オブジェクトを取り出します。"""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def _is_transient(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    return bool(_TRANSIENT_RE.search(str(exc)))


class FoundryInsightsGenerator:
    """OpenAI 互換 API 経由で Foundry Models を呼び出す実装。"""

    def __init__(self, settings: FoundrySettings, credential: Any, *, client: Any = None) -> None:
        self._settings = settings
        self._credential = credential
        self._client = client
        self._disabled_params: set[str] = set()
        self._use_json_schema = True

    # -- クライアント --------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from azure.identity import get_bearer_token_provider
        from openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            self._credential, "https://cognitiveservices.azure.com/.default"
        )
        self._client = AzureOpenAI(
            azure_endpoint=self._settings.endpoint,
            azure_ad_token_provider=token_provider,
            api_version=self._settings.api_version,
            timeout=self._settings.timeout_seconds,
            max_retries=0,  # リトライは本クラスで制御する
        )
        return self._client

    # -- リクエスト構築 ------------------------------------------------------

    def _response_format(self) -> dict[str, Any]:
        if not self._use_json_schema:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": SCHEMA_NAME,
                "strict": True,
                "schema": INSIGHTS_JSON_SCHEMA,
            },
        }

    def _base_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._settings.deployment,
            "max_completion_tokens": self._settings.max_output_tokens,
        }
        if self._settings.reasoning_effort:
            kwargs["reasoning_effort"] = self._settings.reasoning_effort
        if self._settings.temperature is not None:
            kwargs["temperature"] = self._settings.temperature
        return {k: v for k, v in kwargs.items() if k not in self._disabled_params}

    def _drop_unsupported(self, exc: Exception, kwargs: dict[str, Any]) -> bool:
        """エラーメッセージから未対応パラメーターを特定して無効化します。"""
        message = str(exc)
        if not _UNSUPPORTED_PARAM_RE.search(message):
            return False
        for name in ("reasoning_effort", "temperature", "max_completion_tokens"):
            if name in kwargs and name in message:
                self._disabled_params.add(name)
                if name == "max_completion_tokens":
                    self._disabled_params.discard("max_tokens")
                return True
        if self._use_json_schema and ("json_schema" in message or "response_format" in message):
            self._use_json_schema = False
            return True
        return False

    def _call_chat(self, messages: list[dict[str, str]]) -> tuple[str, Any]:
        client = self._get_client()
        kwargs = self._base_kwargs()
        if "max_completion_tokens" in self._disabled_params:
            kwargs["max_tokens"] = self._settings.max_output_tokens
        kwargs["response_format"] = self._response_format()
        response = client.chat.completions.create(messages=messages, **kwargs)
        content = response.choices[0].message.content or ""
        return content, response

    def _call_responses(self, messages: list[dict[str, str]]) -> tuple[str, Any]:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self._settings.deployment,
            "max_output_tokens": self._settings.max_output_tokens,
            "input": [
                {"role": message["role"], "content": message["content"]} for message in messages
            ],
        }
        if self._settings.reasoning_effort and "reasoning_effort" not in self._disabled_params:
            kwargs["reasoning"] = {"effort": self._settings.reasoning_effort}
        if self._use_json_schema:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": SCHEMA_NAME,
                    "strict": True,
                    "schema": INSIGHTS_JSON_SCHEMA,
                }
            }
        else:
            kwargs["text"] = {"format": {"type": "json_object"}}
        response = client.responses.create(**kwargs)
        content = getattr(response, "output_text", "") or ""
        return content, response

    def _invoke(self, messages: list[dict[str, str]]) -> tuple[str, Any]:
        if self._settings.api_style == "responses":
            return self._call_responses(messages)
        return self._call_chat(messages)

    # -- 公開 API ------------------------------------------------------------

    def generate(self, article: NormalizedArticle, body_text: str | None) -> InsightsResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(article, body_text)},
        ]
        started = time.perf_counter()
        max_attempts = max(1, self._settings.max_retries + 1)
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                content, response = self._invoke(messages)
            except Exception as exc:  # noqa: BLE001 - SDK 例外の型は実装依存
                last_error = exc
                if self._drop_unsupported(exc, self._base_kwargs()):
                    log_warning("foundry.parameter.disabled", errorType=type(exc).__name__)
                    continue
                if not _is_transient(exc) or attempt >= max_attempts:
                    raise FoundryError(
                        f"foundry call failed: {type(exc).__name__}",
                        category="transient" if _is_transient(exc) else "permanent",
                    ) from exc
                self._sleep(attempt)
                continue

            try:
                payload = _extract_json(content)
                insights = ArticleInsights.model_validate(payload)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                log_warning(
                    "foundry.output.invalid",
                    attempt=attempt,
                    errorType=type(exc).__name__,
                    outputLength=len(content or ""),
                )
                if attempt >= max_attempts:
                    raise FoundryError("model output failed schema validation", category="schema") from exc
                messages = messages[:2] + [
                    {
                        "role": "user",
                        "content": (
                            "直前の出力は指定した JSON スキーマに一致しませんでした。"
                            "説明やコードブロックを付けず、"
                            "スキーマに厳密に一致する JSON オブジェクトのみを出力してください。"
                        ),
                    }
                ]
                continue

            usage = getattr(response, "usage", None)
            result = InsightsResult(
                insights=insights,
                deployment=self._settings.deployment,
                model_version=getattr(response, "model", None),
                prompt_tokens=getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None),
                completion_tokens=(
                    getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None)
                ),
                attempts=attempt,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            log_info(
                "foundry.completed",
                deployment=result.deployment,
                modelVersion=result.model_version,
                promptTokens=result.prompt_tokens,
                completionTokens=result.completion_tokens,
                attempts=result.attempts,
                durationMs=result.duration_ms,
            )
            return result

        raise FoundryError(
            f"foundry call exhausted retries: {type(last_error).__name__ if last_error else 'unknown'}",
            category="transient",
        )

    @staticmethod
    def _sleep(attempt: int) -> None:
        delay = min(2.0 ** attempt, 30.0) + random.uniform(0, 0.5)
        time.sleep(delay)


def build_generator(settings: FoundrySettings, credential: Any) -> InsightsGenerator:
    """設定に応じた :class:`InsightsGenerator` を返します。"""
    return FoundryInsightsGenerator(settings, credential)
