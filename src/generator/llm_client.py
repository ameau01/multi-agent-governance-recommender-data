"""Thin wrapper around the Anthropic SDK with automatic prompt caching.

Loads prompt templates from `prompts/`, performs substitution, calls the model,
strips accidental markdown fencing, and logs the prompt/response pair to
`intermediates/NN/passN_llm_log.json` for debugging.

Environment variables (loaded from .env via python-dotenv at module import):

    ANTHROPIC_API_KEY   (required) — Anthropic console API key
    LANGSMITH_TRACING   (optional) — "true" enables LangSmith tracing of every API call
    LANGSMITH_API_KEY   (required if tracing enabled) — LangSmith API key
    LANGSMITH_PROJECT   (optional) — LangSmith project name; default project used if unset

# Automatic prompt caching

Prompts use a simple section structure that this module parses into cache
blocks. The structure:

    SYSTEM:
    [system content - always cached]

    USER:
    [stable boilerplate that's the same across all scenarios]

    <<<CACHE>>>

    [per-scenario stable content like Pass 1 JSON]

    <<<CACHE>>>

    [variable content that changes within a scenario]

What this gives you:
  - The SYSTEM block is always cached (cross-scenario, cross-call).
  - Each `<<<CACHE>>>` marker creates a cache breakpoint in the USER message.
  - The Anthropic API matches the longest cached prefix on subsequent calls.

For Pass 1: one `<<<CACHE>>>` marker after the stable boilerplate (TIME-PATTERN
RULES, HEALTHY BASELINES, OUTPUT SCHEMA, REQUIREMENTS). The per-scenario
SCENARIO/BUSINESS CONTEXT/PASS 1 METRIC RANGES sits in the variable tail.
Cross-scenario, the system + boilerplate prefix is cached → ~67% input cost
savings on the cached portion.

For Pass 2: two `<<<CACHE>>>` markers. First marker after the stable boilerplate;
second marker after the Pass 1 JSON. The per-scenario correlation rules sit in
the variable tail. Within Pass 2 retries on the same scenario, the Pass 1 JSON
hit the cache → ~90% input cost savings on the (large) Pass 1 JSON portion.

For smoke test: no `<<<CACHE>>>` markers needed; only the system block is cached.

Caching is fully automatic — call sites don't need to think about it. The prompt
template's structure dictates the cache layout.

# Optional LangSmith tracing

When LANGSMITH_TRACING is "true", the Anthropic client is automatically wrapped
with `langsmith.wrappers.wrap_anthropic`. Tracing is transparent — no call-site
changes needed. To group per-scenario LLM calls into a single LangSmith run
(so Pass 1 + Pass 2 + smoke test for one scenario appear under one parent),
decorate the calling function with `@langsmith.traceable(name="...", metadata=...)`.
"""

from __future__ import annotations
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def _log(msg: str = "", *, end: str = "\n") -> None:
    """Print one progress line prefixed with [HH:MM:SS], always flushed.

    Empty / whitespace-only messages pass through unstamped so spacing stays clean.
    """
    if not msg.strip():
        print(msg, end=end, flush=True)
        return
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", end=end, flush=True)

# Load .env at module import. Idempotent — safe to call from cli.py as well.
load_dotenv()

import anthropic

from generator.constants import LLM_TEMPERATURE, SDK_MAX_RETRIES


CACHE_MARKER = "<<<CACHE>>>"
EPHEMERAL_CACHE = {"type": "ephemeral"}


# ============================================================
# Anthropic client construction (with optional LangSmith wrapping)
# ============================================================
def _make_anthropic_client() -> "anthropic.Anthropic":
    """Construct an Anthropic client, optionally wrapped for LangSmith tracing.

    Tracing activates when LANGSMITH_TRACING env var is "true" or "1".
    The LangSmith wrapper has the same interface as the raw Anthropic client.
    Project name is picked up from the LANGSMITH_PROJECT env var.
    """
    # SDK-level retries absorb transient 5xx, network blips, and brief
    # rate-limit windows. Bumped from default (2) to SDK_MAX_RETRIES via .env.
    raw_client = anthropic.Anthropic(max_retries=SDK_MAX_RETRIES)  # reads ANTHROPIC_API_KEY from env

    tracing_enabled = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1")
    if tracing_enabled:
        from langsmith.wrappers import wrap_anthropic
        return wrap_anthropic(raw_client)
    return raw_client


# ============================================================
# Prompt parsing — splits the template into cache-able blocks
# ============================================================
_SECTION_RE = re.compile(r"^(SYSTEM|USER):\s*$", re.MULTILINE)


def _parse_prompt_template(text: str) -> tuple[str, list[str]]:
    """Parse a prompt template into (system_content, user_blocks).

    The template must contain a `SYSTEM:` line and a `USER:` line. Everything
    between SYSTEM: and USER: is the system content. Everything after USER: is
    the user content, optionally split into multiple blocks by `<<<CACHE>>>`
    markers.

    Returns:
        (system, [user_block_1, user_block_2, ..., user_block_N])

        - `system` is the system content (str).
        - The list has 1+ entries; the LAST entry is the variable (uncached) tail.
          The preceding entries (if any) are the cached prefixes.

    Raises:
        ValueError: if SYSTEM: or USER: markers are missing.
    """
    matches = list(_SECTION_RE.finditer(text))
    if len(matches) != 2:
        raise ValueError(
            f"Prompt must contain exactly one SYSTEM: and one USER: marker, "
            f"got {len(matches)} section markers."
        )
    system_match, user_match = matches
    if system_match.group(1) != "SYSTEM" or user_match.group(1) != "USER":
        raise ValueError(
            "Prompt sections must appear in order: SYSTEM: then USER:."
        )

    system_content = text[system_match.end():user_match.start()].strip()
    user_full = text[user_match.end():].strip()

    user_blocks = [b.strip() for b in user_full.split(CACHE_MARKER)]
    return system_content, user_blocks


def _build_message_content(
    user_blocks: list[str],
    substitutions: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the `messages[0].content` list with cache_control on every block
    except the last (variable) one.

    Each block is formatted with the substitutions dict (str.format style).
    Empty blocks are skipped — they don't consume cache slots.
    """
    content: list[dict[str, Any]] = []
    for i, block in enumerate(user_blocks):
        if not block:
            continue
        rendered = block.format(**substitutions)
        is_last = (i == len(user_blocks) - 1)
        item: dict[str, Any] = {"type": "text", "text": rendered}
        if not is_last:
            # All blocks except the final variable tail get cached.
            item["cache_control"] = EPHEMERAL_CACHE
        content.append(item)
    return content


def _strip_markdown_fencing(response_text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fencing if the model emitted it
    despite the prompt's instructions."""
    text = response_text.strip()
    if text.startswith("```"):
        # Strip the opening fence (with optional language tag)
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        # Strip the closing fence
        if text.endswith("```"):
            text = text[:-3].rstrip()
    return text


# ============================================================
# LLM client
# ============================================================
class LLMClient:
    """Anthropic SDK wrapper with automatic prompt caching and optional tracing.

    Usage:
        client = LLMClient(model="claude-haiku-4-5-20251001")
        response = client.call(
            prompt_path=PASS1_PROMPT_PATH,
            substitutions={
                "scenario_id": "01",
                "scenario_name": "Chronic Underutilization",
                "tiers_required": "compute",
                ...
                "healthy_baselines_block": "...",  # large, stable across scenarios
            },
            log_path=intermediates_dir / "01" / "pass1_llm_log.json",
            metadata={"scenario_id": "01", "phase": "pass1"},  # for LangSmith trace
        )
    """

    def __init__(
        self,
        model: str,
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = 8192,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = _make_anthropic_client()

    def call(  # noqa: D401
        self,
        prompt_path: Path,
        substitutions: dict[str, Any],
        log_path: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Render the prompt template (with caching) and call the model.

        The prompt template uses Python str.format syntax and the SYSTEM:/USER:
        section structure documented in this module's docstring. `<<<CACHE>>>`
        markers in the USER section create cache breakpoints automatically.

        Args:
            prompt_path: Path to a .txt prompt template (e.g. prompts/pass1.txt).
            substitutions: Dict for `.format(**substitutions)` substitution.
                Must include keys for every `{placeholder}` in the template.
            log_path: If provided, writes a JSON log of the prompt + response.
                Used for debugging Pass 1 / Pass 2 outputs.
            metadata: Optional dict attached to the LangSmith trace for this call.
                Ignored when LangSmith tracing is disabled.

        Returns:
            The model's response text, stripped of any markdown fencing.

        Raises:
            FileNotFoundError: if prompt_path doesn't exist.
            KeyError: if substitutions are missing for any prompt placeholder.
            ValueError: if the prompt template is malformed.
            anthropic.APIError: on API failures.
        """
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {prompt_path}")

        template = prompt_path.read_text(encoding="utf-8")
        system_raw, user_blocks_raw = _parse_prompt_template(template)

        system_content = system_raw.format(**substitutions) if system_raw else ""
        user_content = _build_message_content(user_blocks_raw, substitutions)

        system_payload = (
            [{"type": "text", "text": system_content, "cache_control": EPHEMERAL_CACHE}]
            if system_content else []
        )

        # Use streaming — Anthropic SDK requires it for requests that may
        # exceed 10 minutes (which our Pass 1 / Pass 2 calls with
        # max_tokens=64000 can). Streaming has no behavioral difference
        # in the final response shape, just no timeout cap.
        _log(
            f"    streaming response (model={self.model}, "
            f"max_tokens={self.max_tokens})..."
        )
        chunk_count = 0
        with self._client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_payload,
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            # Consume the stream to drive it to completion. We don't print
            # the text chunks (would flood the log with raw JSON); instead
            # we print a dot every 200 chunks as a heartbeat. The dot is
            # intentionally NOT timestamped — it's a single-character
            # continuation on the same line.
            for _ in stream.text_stream:
                chunk_count += 1
                if chunk_count % 200 == 0:
                    print(".", end="", flush=True)
            response = stream.get_final_message()
        if chunk_count >= 200:
            print()  # newline after dot heartbeat
        _log(
            f"    stream complete (chunks={chunk_count}, "
            f"output_tokens={getattr(response.usage, 'output_tokens', '?')})"
        )

        if not response.content or response.content[0].type != "text":
            raise RuntimeError(
                f"Unexpected response shape from model {self.model}: "
                f"content={response.content!r}"
            )
        text = _strip_markdown_fencing(response.content[0].text)

        if log_path is not None:
            _write_log(
                log_path,
                model=self.model,
                temperature=self.temperature,
                system_content=system_content,
                user_content=user_content,
                response_text=text,
                usage=getattr(response, "usage", None),
                metadata=metadata,
            )

        return text


def _write_log(
    log_path: Path,
    *,
    model: str,
    temperature: float,
    system_content: str,
    user_content: list[dict[str, Any]],
    response_text: str,
    usage: Any,
    metadata: dict[str, Any] | None,
) -> None:
    """Persist a JSON log of one LLM call for debugging. Atomic write."""
    import json, os, tempfile
    log_path.parent.mkdir(parents=True, exist_ok=True)
    usage_dict: dict[str, Any] = {}
    if usage is not None:
        for attr in (
            "input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens",
        ):
            val = getattr(usage, attr, None)
            if val is not None:
                usage_dict[attr] = val
    payload = {
        "model": model,
        "temperature": temperature,
        "system": system_content,
        "user_blocks": user_content,
        "response": response_text,
        "usage": usage_dict,
        "metadata": metadata or {},
    }
    fd, tmp_str = tempfile.mkstemp(
        suffix=".tmp", prefix=log_path.name + ".", dir=str(log_path.parent),
    )
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, log_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ============================================================
# Batch API support — Phase B.6 deliverable
# ============================================================
class BatchSubmitter:
    """Anthropic Batches API wrapper for asynchronous batch submission.

    Same models, same prompts, same parameters as `LLMClient` — therefore the
    same response quality. The only differences are:
        - 50% pricing
        - Asynchronous (submit → poll → retrieve)
        - Typical wall-clock: 5–30 minutes; 24-hour SLA worst case

    Activated via the `DATAGEN_BATCH_MODE=true` env var (constant defined in
    `constants.py:BATCH_MODE_ENV_VAR`). When inactive, the pipeline falls back
    to `LLMClient` (interactive sync calls).

    Usage pattern (called by `pipeline.py`):

        batcher = BatchSubmitter(model=PASS1_MODEL)
        for scenario_id in scenario_ids:
            batcher.enqueue(
                custom_id=f"pass1-{scenario_id}",
                prompt_path=PASS1_PROMPT_PATH,
                substitutions={...},
                metadata={"scenario_id": scenario_id, "phase": "pass1"},
            )
        results = batcher.submit_and_wait(poll_interval_seconds=30)
        # results: dict[custom_id, str] — model response text per custom_id

    Cache control is applied identically to LLMClient — the prompt structure
    drives the cache layout. Cache hits/misses are visible in per-result usage.

    Phase B.6 implementation references:
      - Anthropic Batches API docs: https://docs.anthropic.com/en/api/creating-message-batches
      - Max 10,000 requests per batch (we use ~18–90).
      - Max 256 MB total request size (our Pass 1 batch is ~5–15 MB).
      - Results retrievable for 29 days post-completion.
    """

    def __init__(
        self,
        model: str,
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = 8192,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = _make_anthropic_client()
        self._queue: list[dict[str, Any]] = []

    def enqueue(
        self,
        custom_id: str,
        prompt_path: Path,
        substitutions: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a request to the pending batch.

        Renders the prompt template (same caching layout as LLMClient.call)
        and stores the resulting message structure under `custom_id`. The
        request is sent when `submit_and_wait()` is called.
        """
        raise NotImplementedError(
            "Phase B.6 — build the per-request payload using the same parsing "
            "helpers (_parse_prompt_template, _build_message_content), append "
            "to self._queue with the custom_id. See BUILD_PLAN.md §B.6."
        )

    def submit_and_wait(
        self,
        poll_interval_seconds: int = 30,
        timeout_seconds: int = 3600,
    ) -> dict[str, str]:
        """Submit the queued batch to Anthropic and poll until complete.

        Args:
            poll_interval_seconds: How often to check batch status.
            timeout_seconds: Maximum wait time before raising TimeoutError.

        Returns:
            dict mapping custom_id → response text (markdown-stripped).
            Failed requests are included with sentinel ``None`` values — caller
            is expected to handle gracefully.

        Raises:
            TimeoutError: if the batch hasn't completed within timeout_seconds.
            anthropic.APIError: on batch submission failures.
        """
        raise NotImplementedError(
            "Phase B.6 — use self._client.messages.batches.create(requests=...), "
            "poll via self._client.messages.batches.retrieve(batch.id), and read "
            "results via self._client.messages.batches.results(batch.id). "
            "Reference pattern in the BatchSubmitter docstring above."
        )


def use_batch_mode() -> bool:
    """Read DATAGEN_BATCH_MODE from environment. True iff explicitly set to truthy."""
    raw = os.getenv(
        "DATAGEN_BATCH_MODE",
        "true" if False else "false",   # default from constants — read lazily to avoid import cycle
    )
    return raw.lower() in ("true", "1")
