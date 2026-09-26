#!/usr/bin/env python3
"""Cold prefill bench: unique-salt prompts (zero prefix-cache hits), thinking off,
temp 0, prefill tok/s = prompt tokens / TTFT. Run it twice and read the second
pass — the first request of each size after a boot pays one-time JIT/allocation.

    python3 bench/prefill.py --base http://127.0.0.1:8888 --sizes 8192 16384 32768 131072
"""
import argparse, json, math, time, urllib.request, uuid

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8888")
ap.add_argument("--sizes", type=int, nargs="+", default=[8192, 16384, 32768])
ap.add_argument("--reps", type=int, default=3)
ap.add_argument("--out", default="")
a = ap.parse_args()

model = json.load(urllib.request.urlopen(a.base + "/v1/models", timeout=10))["data"][0]["id"]


def ttft(prompt):
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0, "max_tokens": 8, "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(a.base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t, first, usage = time.time(), None, None
    with urllib.request.urlopen(req, timeout=1800) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            d = json.loads(line[6:])
            usage = d.get("usage") or usage
            for c in d.get("choices", []):
                if c.get("delta", {}).get("content") and first is None:
                    first = time.time()
    return first - t, usage["prompt_tokens"]


rows = []
for size in a.sizes:
    for rep in range(a.reps):
        header = f"[prefill-bench {uuid.uuid4()}]\nIgnore the filler below. Reply with the single word OK.\n"
        footer = "\nReply OK."
        prompt = header + " the" * max(1, size - math.floor(len(header + footer) / 4 + .5)) + footer
        s, n = ttft(prompt)
        row = {"target": size, "rep": rep, "prompt_tokens": n, "ttft_s": round(s, 3), "tok_s": round(n / s, 1)}
        rows.append(row)
        print(json.dumps(row), flush=True)
if a.out:
    open(a.out, "w").write(json.dumps({"model": model, "prefill": rows}, indent=2))
