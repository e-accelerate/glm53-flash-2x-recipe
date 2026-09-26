# GLM-5.3-Flash on two GB10 boxes — ASUS GX10 + DGX Spark, dual-rail

A tuned, measured recipe for serving **GLM-5.3-Flash (EXL3 4bpw, 850k context)** across two GB10
machines. The serving stack is MiaAI-Lab's
[GLM-5.3-Flash-EXL3-2x-DGX-Sparks](https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks)
kit, pinned to a tested commit. This repo adds the settings, a small launcher patch for mixed and
dual-rail pairs, and the measurements behind every choice.

One config file, two commands. The weights, drafter and sampling are the kit's own, so the model's
output quality is unchanged.

## Measured (2026-09-26, this exact recipe)

GX10 head + DGX Spark worker, TP=2, both ConnectX-7 rails (MTU 9000), driver 580.173.02.
Unique-salt cold prompts, thinking off; decode = the kit's `tests/bench_decode.py`
(temp 0, 5 × 400 tokens, median).

| | this recipe | kit's published numbers¹ |
|---|---:|---:|
| prefill 8k / 16k / 32k | **1,582 / 1,635 / 1,662 tok/s** | 1,492 / 1,554 / 1,428 |
| prefill 128k | **1,655 tok/s** | 1,562 |
| decode, structured | **78.7 tok/s** | 65.1 |
| decode, prose | **33.9 tok/s** | 27.1 |
| decode, code | **54.0 tok/s** | — |
| follow-up agent turn on a 34k / 72k context | **1.5 s / 0.7 s** TTFT | — |
| boot to ready | **~300 s** (210 s warm) | — |
| swap written while loading | **~3 MB** (was 6.4 GB) | — |
| KV capacity at 850k context | 1.85× one full request | — |

¹ The kit README's E3 prefill table (sparkDash, 2026-09-07) and its `bench_decode` lab numbers
(2026-08-30). Different dates and client tools, so read them as reference points, not as a
controlled A/B. The controlled A/Bs behind each setting are in
[docs/field-report-2026-09-26.md](docs/field-report-2026-09-26.md).

## What this recipe changes, and why

| setting | effect (measured on this pair) |
|---|---|
| kit `main` @ `70b2f33` + `LOAD_FORMAT=` (auto loader, kit PR #251) | boots 554 → 300 s; swap per load 6.4 GB → ~3 MB; follow-up turns 3.8 → 1.5 s at 34k |
| image built locally from the pinned kit (first run, 10–30 min) | the published GHCR image lacks the FAST decode kernel and #251 |
| `GLM53_EXL3_MOE_FAST=1` | +8–10 % per decode step, all workloads |
| `GLM53_DENSE_FP8=dense,kda` + `GLM53_ADAPTIVE_K=ema` + TP1 drafter | the kit's decode levers, stacked |
| **`GLM53_KDA_BF16_LARGE_M=1`** | FP8 KDA alone silently costs ~12 % prefill; this gives it back with decode unchanged |
| `MAX_NUM_BATCHED_TOKENS=7168` | +4–5 % prefill over 2048 once both rails are up |
| empty `NCCL_IB_GID_INDEX` + both HCAs listed | rail 2 actually engages; survives the GID-table shift after reboots |
| adaptive-k runtime `set [3,5,7]`, margin 0.5 | best measured on code workloads |

How close this runs to the hardware limits, and what did *not* help, is in
[docs/ceilings.md](docs/ceilings.md). In short: decode steps run at ~85–95 % of memory bandwidth,
and prefill has no single bottleneck left.

## Quick start

Prerequisites: two GB10 boxes (DGX Spark or ASUS GX10), both ConnectX-7 ports cabled and
addressed (rail 1 and rail 2, MTU 9000), passwordless SSH head → worker over the fabric, docker
with the NVIDIA runtime, ~200 GB free on each node.

```bash
git clone https://github.com/geekyabhijit/glm53-flash-2x-recipe.git
cd glm53-flash-2x-recipe
$EDITOR recipe.env      # your node IPs, worker user, interface names
./run.sh                # first run: fetches the kit, builds the image (10–30 min), downloads ~164 GiB
```

`./run.sh restart` applies config changes, `./stop.sh` stops both ranks, and `./run.sh status`
shows health. The API is OpenAI-compatible on `:8888`, with served model name `GLM-5.3-Flash-EXL3`.

Benchmarks:

```bash
python3 bench/prefill.py --base http://127.0.0.1:8888 --sizes 8192 16384 32768 131072
python3 bench/followup_ttft.py --base http://127.0.0.1:8888
python3 kit/tests/bench_decode.py --phase prose --runs 5 --max-tokens 400 --skip-coherence --out prose.json
```

### Verification status

- **Verified on the pair:** every setting in `recipe.env`, served from the pinned kit commit with
  an equivalent launcher patch (all numbers above). On a fresh clone, `run.sh` also completed its
  kit fetch, patch, dual-rail preflight and image build.
- **Not yet verified end to end:** `run.sh`'s final ship-to-worker and serve step. That first
  test run was stopped partway so a live session wasn't interrupted. Issues and reports are welcome.

## The launcher patch

[`patches/dual-rail-launcher.patch`](patches/dual-rail-launcher.patch) touches only the kit's
`start.sh`, and every change is opt-in. With defaults, behaviour is identical to upstream (the
kit's 14 launcher tests pass on the patched file).

- **An empty `NCCL_IB_GID_INDEX`** means NCCL's per-HCA RoCEv2 auto-selection, and the GID preflight
  is skipped for it. Dual-rail pairs need this, because rail 2's GID table shifts after a reboot.
- **`WORKER_DOCKER_SUDO=1`** runs the worker's docker calls through passwordless sudo, so no
  docker-group grant is needed.
- **`BIND_HOST` / `API_HOST`**: bind the API to one address (for example a tailnet IP) instead of
  `0.0.0.0`. Health checks, warmup and banners follow it.

## Operational notes for GB10

- **Headless DGX Sparks can overheat.** On GB10 the fan curve follows system power draw, not
  temperature, and a Spark run over SSH with no display can stop cooling under load. Attach a
  display or a USB device drawing ≥5 W, and consider an SM clock cap (`nvidia-smi -lgc 0,2200`).
  The GX10 does not show this.
- **Reboot before believing a NIC ceiling.** Long-uptime ConnectX state measured a hard
  ~15 Gb/s per rail and read clean on every counter. A power cycle restored full speed.
- Right after a boot the head can show ~2 GiB free for a couple of minutes. Let it settle before
  sending a 100k+ prompt.

## Credits

- **[MiaAI-Lab](https://github.com/MiaAI-Lab)**: the entire serving kit (vLLM overlay, EXL3 E3
  prefill kernels, FAST decode kernel, adaptive-k, dense FP8, #251 loader/APC work). This repo
  is a recipe on top of it.
- **[turboderp / ExLlamaV3](https://github.com/turboderp-org/exllamav3)**: EXL3 quantization and kernels.
- **[inco.ai](https://inco.ai)**: the DFlash2 drafter (`incoai/GLM-5.3-Flash-DFlash2`, CC BY-NC-ND 4.0, research use).
- **Z.ai**: GLM-5.3-Flash.

## License

AGPL-3.0, the same as the kit this recipe patches (see [LICENSE](LICENSE)). The model weights
and the drafter carry their own licenses.
