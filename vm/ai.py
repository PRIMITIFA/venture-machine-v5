"""AI layer. Two ways to run Claude:

- anthropic : the Claude API (needs ANTHROPIC_API_KEY). Costs are counted against the idea's cap.
- claude-cli: the Claude Code CLI (`claude -p`), runs on your Claude subscription.

The AI only sorts, labels and writes. Numbers come from APIs or web pages with a source (golden rule 1).
Every answer is JSON, checked against a pydantic model; a bad answer is retried once with the error.
"""
import base64
import json
import os
import pathlib
import shutil
import subprocess

from pydantic import BaseModel, ValidationError

from . import budget
from .config import S
from .util import extract_json

PRICES = {  # USD per 1M tokens (input, output)
    "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8.0, 40.0),
}
WEB_SEARCH_USD = 0.01

SYSTEM = """You are the research engine of Zero to Launch, a strict process that takes a business idea to a
validated plan. Golden rules:
1. Never invent numbers. Every volume, price, traffic, revenue or count must come from the data given to you or
   from a web page you actually opened, with its URL. If you do not know, say "unknown" and lower confidence.
2. Thresholds are fixed before results; do not bend them to make an idea pass.
3. Be blunt and specific. Short sentences. No hype.
4. Answer with ONE JSON object only, no prose around it.
"""


class AIError(Exception):
    pass


def provider():
    p = S.ai_provider
    if p in ("anthropic", "claude-cli", "fake"):
        return p
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if shutil.which("claude"):
        return "claude-cli"
    return "none"


# Tests swap this for a function(full_prompt, schema_cls, web, model) -> dict
FAKE = None


def ask_json(task, schema_cls: type[BaseModel], *, web=False, smart=True, images=(), context=None):
    model = S.model_smart if smart else S.model_fast
    rules = S.house_rules.strip()
    prompt = task.strip()
    if context:
        prompt += "\n\n## Data you can use (with sources)\n" + (context if isinstance(context, str) else json.dumps(context, ensure_ascii=False, indent=1)[:60000])
    if rules:
        prompt += "\n\n## Owner's house rules (an idea that breaks one must be flagged)\n" + rules[:4000]
    prompt += ("\n\n## Output\nReturn ONLY one JSON object that matches this JSON schema (no markdown):\n"
               + json.dumps(schema_cls.model_json_schema(), ensure_ascii=False))
    p = provider()
    last_err = ""
    for attempt in range(2):
        full = prompt if not last_err else prompt + f"\n\nYour previous answer was invalid: {last_err}\nFix it and return valid JSON only."
        if p == "fake" or FAKE:
            data = FAKE(prompt, schema_cls, web, model)
            return schema_cls.model_validate(data)
        if p == "anthropic":
            text = _anthropic(full, model, web, images)
        elif p == "claude-cli":
            text = _cli(full, model, web, images)
        else:
            raise AIError("no AI available: set ANTHROPIC_API_KEY or install Claude Code (`claude` on PATH)")
        try:
            return schema_cls.model_validate(extract_json(text))
        except (ValueError, ValidationError) as e:
            last_err = str(e)[:1500]
    raise AIError(f"AI returned invalid JSON twice: {last_err[:300]}")


def _anthropic(prompt, model, web, images):
    import anthropic
    budget.check(0.25 if web else 0.08)
    client = anthropic.Anthropic()
    content = []
    for img in images:
        data = base64.standard_b64encode(pathlib.Path(img).read_bytes()).decode()
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]
    kw = {"model": model, "max_tokens": 16000, "system": SYSTEM, "messages": messages}
    if web:
        kw["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}]
    cin, cout, searches = 0, 0, 0
    resp = None
    for _ in range(6):  # continue server-tool turns that pause
        try:
            resp = client.messages.create(**kw)
        except anthropic.APIStatusError as e:
            raise AIError(f"Claude API {e.status_code}: {e.message}")
        except anthropic.APIConnectionError as e:
            raise AIError(f"Claude API connection error: {e}")
        u = resp.usage
        cin += (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        cout += u.output_tokens or 0
        stu = getattr(u, "server_tool_use", None)
        searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        break
    pin, pout = PRICES.get(model, (4.0, 20.0))
    budget.record("anthropic", model, cin / 1e6 * pin + cout / 1e6 * pout + searches * WEB_SEARCH_USD)
    if resp.stop_reason == "refusal":
        raise AIError("Claude declined this request")
    return "".join(b.text for b in resp.content if b.type == "text")


def _cli(prompt, model, web, images):
    exe = shutil.which("claude")
    if not exe:
        raise AIError("claude CLI not found on PATH")
    if images:
        prompt = "Look at these screenshots first (use the Read tool): " + ", ".join(str(i) for i in images) + "\n\n" + prompt
    tools = (["WebSearch", "WebFetch"] if web else []) + (["Read"] if images else [])
    cmd = [exe, "-p", "--output-format", "json", "--model", model, "--append-system-prompt", SYSTEM,
           "--strict-mcp-config", "--permission-mode", "default",
           "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit", "Agent", "Task"]
    if tools:
        cmd += ["--allowedTools", *tools]
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # make the CLI use the subscription login
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=1200, env=env, cwd=str(S.data_dir))
    except subprocess.TimeoutExpired:
        raise AIError("claude CLI timed out after 20 minutes")
    if r.returncode != 0 and not r.stdout.strip():
        raise AIError(f"claude CLI failed: {r.stderr.strip()[:400]}")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.stdout
    if d.get("is_error"):
        raise AIError(f"claude CLI error: {str(d.get('result'))[:400]}")
    budget.record("claude-cli", model, d.get("total_cost_usd") or 0, counted=S.count_cli_cost)
    return d.get("result") or ""
