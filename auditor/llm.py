"""Nebius Token Factory client with a hard spend cap.

Token Factory has no server-side spending limit, so every call goes through
`chat()`, which records usage in a local ledger and refuses to call the API
once the cumulative cost reaches SPEND_CAP_USD.
"""

import json
import os
import re
import threading
import time
from pathlib import Path

import json_repair
from dotenv import load_dotenv
from openai import OpenAI

from . import memo
from .memo import recall

load_dotenv()

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
SPEND_CAP_USD = float(os.getenv("SPEND_CAP_USD", "35"))
# Token Factory bills VAT on top of the token prices (21% in Spain). With VAT_RATE set, every cost
# counted, and so the cap, is what is actually charged; at 0 they are the prices before tax.
VAT_RATE = float(os.getenv("VAT_RATE", "0"))
LEDGER = Path(".spend.json")
MAX_OUTPUT_TOKENS = 24000  # includes the reasoning tokens of the Nemotron models

# role -> (model id, USD per 1M input tokens, USD per 1M output tokens).
# Prices as returned by GET /v1/models?verbose=true on 2026-10-13.
MODELS = {
    "ultra": (os.getenv("NEMOTRON_ULTRA", "nvidia/Nemotron-3-Ultra-550b-a55b"), 1.00, 3.00),
    "super": (os.getenv("NEMOTRON_SUPER", "nvidia/nemotron-3-super-120b-a12b"), 0.30, 0.90),
    "nano": (os.getenv("NEMOTRON_NANO", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"), 0.06, 0.24),
    # No NVIDIA vision model is served on the public endpoint; used only to transcribe scanned PDFs.
    "vision": (os.getenv("VISION_MODEL", "openbmb/MiniCPM-V-4_5"), 0.658, 1.11),
}

# Cost of the calls made by this process, per role, and one entry per call sent.
session_cost: dict[str, float] = {}
calls: list[dict] = []

# When set, every model reply is saved there, numbered in call order.
trace_dir: Path | None = None

NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}
# The Nemotron reasoning mode often runs away: it spends the whole output budget
# thinking and never answers (a 24000-token plan call, 80 s, then answered in
# 2200 tokens and 8 s without it). So it is off by default, and on only where
# turning it off cost correct results: extracting claims, choosing assumptions
# and writing code. Those calls set a low max_tokens so that a runaway is cut
# early and answered again without reasoning.


PROVIDER_ERROR = re.compile(r"^\s*\[ERROR:", re.IGNORECASE)


class ProviderError(RuntimeError):
    """The endpoint answered with an error message instead of a reply."""


class SpendCapReached(RuntimeError):
    pass


_log = threading.local()


def tag_log(tag: str) -> None:
    """Prefix this thread's progress lines, e.g. with the id of the claim it works on."""
    _log.tag = tag


def say(message: str) -> None:
    tag = getattr(_log, "tag", "")
    print(f"  [{tag}] {message}" if tag else f"  {message}", flush=True)


_client = None
_ledger_lock = threading.Lock()


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=BASE_URL, api_key=os.environ["NEBIUS_API_KEY"], timeout=900)
    return _client


def spent() -> float:
    return json.loads(LEDGER.read_text())["usd"] if LEDGER.exists() else 0.0


def chat(role: str, messages: list[dict], thinking: bool = False, **kwargs) -> str:
    """Ask a model. Reasoning is off unless the call asks for it (see NO_THINKING)."""
    if not thinking:
        kwargs.setdefault("extra_body", NO_THINKING)
    text, truncated = complete(role, messages, **kwargs)
    if truncated and kwargs.get("extra_body") != NO_THINKING:
        # runaway reasoning used up the output: ask again without it
        text, _ = complete(role, messages, **{**kwargs, "extra_body": NO_THINKING})
    return text


def complete(role: str, messages: list[dict], **kwargs) -> tuple[str, bool]:
    """Return (reply, truncated).

    The endpoint does not return the same text twice for the same request, so
    each request is sent once and its reply recorded (see memo.py).
    """
    model, price_in, price_out = MODELS[role]
    purpose = kwargs.pop("purpose", "")  # a label for the call log, not sent to the API
    kwargs.setdefault("max_tokens", MAX_OUTPUT_TOKENS)
    kwargs.setdefault("temperature", 0)
    kwargs.setdefault("seed", 0)

    def request() -> dict:
        for wait in (0, 15):  # a timeout on the provider's side tends to repeat: one retry, then give up
            time.sleep(wait)
            reply = send()
            # The endpoint sometimes returns its own failure as the reply text. It is not an answer: it is
            # retried, and never recorded, or every later run of the paper would replay it.
            if not PROVIDER_ERROR.match(reply["text"]):
                return reply
            say(f"  {role}: provider error in place of a reply ({reply['text'][:80]}), retrying")
        raise ProviderError(f"{role}: the provider kept failing: {reply['text'][:200]}")

    def send() -> dict:
        total = spent()
        if total >= SPEND_CAP_USD:
            raise SpendCapReached(f"Spent ${total:.2f} of ${SPEND_CAP_USD:.2f} cap")
        started = time.monotonic()
        response = client().chat.completions.create(model=model, messages=messages, **kwargs)
        usage = response.usage
        cost = (usage.prompt_tokens * price_in + usage.completion_tokens * price_out) / 1e6 * (1 + VAT_RATE)
        with _ledger_lock:
            LEDGER.write_text(json.dumps({"usd": spent() + cost}))
            session_cost[role] = session_cost.get(role, 0.0) + cost
            calls.append({"role": role, "for": getattr(_log, "tag", "") or "paper", "purpose": purpose,
                          "seconds": round(time.monotonic() - started, 1), "in": usage.prompt_tokens,
                          "out": usage.completion_tokens, "usd": round(cost, 4)})
        truncated = response.choices[0].finish_reason == "length"
        say(f"  {role}: {usage.prompt_tokens} in / {usage.completion_tokens} out = ${cost:.4f}"
            + (" (truncated)" if truncated else ""))
        return {"text": strip_reasoning(response.choices[0].message.content or ""), "truncated": truncated}

    record = {"model": model, "messages": messages, "params": kwargs}
    if memo.attempt > 1 and role != "vision":  # a new attempt keeps the transcription and re-asks the rest
        record["attempt"] = memo.attempt
    reply = recall("llm", record, request)
    text, truncated = reply["text"], reply["truncated"]
    if trace_dir:
        with _ledger_lock:
            trace_dir.mkdir(parents=True, exist_ok=True)
            n = len(list(trace_dir.iterdir())) + 1
            prompt = messages[-1]["content"]
            prompt = prompt if isinstance(prompt, str) else prompt[0]["text"]
            (trace_dir / f"{n:03d}_{role}.md").write_text(
                f"# PROMPT (last message, first 3000 chars)\n\n{prompt[:3000]}\n\n# REPLY\n\n{text}\n", encoding="utf-8")
    return text, truncated


LATEX_COMMAND = re.compile(r"(?<!\\)\\(?=[a-z]{2})(?!u[0-9a-fA-F]{4})")


def parse_json(text: str, key: str) -> dict:
    """Parse the JSON object of a model reply, tolerating the usual model mistakes."""
    text = text[text.index("{"): text.rindex("}") + 1]
    # LaTeX commands inside strings (\frac, \nu) are not JSON escapes: keep their backslash.
    text = LATEX_COMMAND.sub(r"\\\\", text)
    try:
        value = json.loads(text)
    except ValueError:
        value = json_repair.loads(text)  # unescaped quotes, trailing commas, arithmetic
    if not isinstance(value, dict) or key not in value:
        raise ValueError(f"no '{key}' field in the reply")
    return value


def chat_json(role: str, messages: list[dict], key: str, **kwargs) -> dict:
    """Like chat(), but return the reply parsed as a JSON object that has `key`."""
    for seed in range(3):  # a new seed gives a new sample
        reply = chat(role, messages, seed=seed, **kwargs)
        try:
            return parse_json(reply, key)
        except ValueError as error:
            say(f"  {role}: unusable JSON reply ({error}), asking again")
            Path("runs").mkdir(exist_ok=True)
            Path("runs/last_invalid_json.txt").write_text(reply, encoding="utf-8")
    raise RuntimeError(f"{role} did not return valid JSON after 3 attempts; see runs/last_invalid_json.txt")


def strip_reasoning(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return re.sub(r"</?think>", "", text).strip()


def extract_code(text: str) -> str:
    """Return the last fenced code block of a model reply, or the reply itself."""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, flags=re.DOTALL)
    return blocks[-1] if blocks else text


if __name__ == "__main__":
    for m in sorted(m.id for m in client().models.list()):
        print(m)
    print(f"Spent so far: ${spent():.4f} / ${SPEND_CAP_USD:.2f}")
