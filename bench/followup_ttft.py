#!/usr/bin/env python3
"""Agent-shaped prefix-cache check: turn 1 sends an N-token context, turn 2 resends the
same conversation plus one assistant and one user message (what omp / hermes / any
coding agent does every turn). Reports both TTFTs.

    python3 bench/followup_ttft.py --base http://127.0.0.1:8888 --sizes 32000 64000
"""
import argparse, json, time, urllib.request, uuid

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8888")
ap.add_argument("--sizes", type=int, nargs="+", default=[32000, 64000])
a = ap.parse_args()
model = json.load(urllib.request.urlopen(a.base + "/v1/models", timeout=10))["data"][0]["id"]


def ask(msgs):
    body = {"model": model, "messages": msgs, "max_tokens": 8, "temperature": 0, "stream": True,
            "stream_options": {"include_usage": True}, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(a.base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t, first, usage = time.time(), None, None
    with urllib.request.urlopen(req, timeout=1800) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            d = json.loads(line[5:])
            if first is None and d.get("choices") and d["choices"][0]["delta"].get("content"):
                first = time.time() - t
            usage = d.get("usage") or usage
    return first, usage


for size in a.sizes:
    ctx = f"[session {uuid.uuid4()}]\n" + "\n".join(
        f"def f{i}(x):\n    return x*{i}+{i % 7}" for i in range(size // 14))
    turn1 = [{"role": "user", "content": ctx + "\nSummarize in one word."}]
    t1, u1 = ask(turn1)
    turn2 = turn1 + [{"role": "assistant", "content": "Functions."},
                     {"role": "user", "content": "Now: how many functions? One number."}]
    t2, u2 = ask(turn2)
    print(json.dumps({"prompt_tokens": u1["prompt_tokens"], "turn1_ttft_s": round(t1, 2),
                      "turn2_ttft_s": round(t2, 2)}), flush=True)
