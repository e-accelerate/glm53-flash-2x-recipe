# How close is this to the hardware? (2026-09-26)

All inputs were measured on this pair, not taken from spec sheets.

## Hardware, per GB10 node (torch in the serving image)

| | measured |
|---|---:|
| DRAM read (`sum`) | 265 GB/s (97 % of the 273 GB/s spec) |
| decode-shaped GEMV, M=8 BF16 | 217 GB/s |
| BF16 GEMM 4096–8192 | 82–97 TFLOPS |
| FP8 GEMM (`_scaled_mm`) | 178–195 TFLOPS |
| NCCL all-reduce, dual-rail CX7 | ~45 GB/s effective |

## What one decode step reads (from the checkpoint's safetensors headers)

The routed experts are the only EXL3 weights (156 GB, 4 bpw). Everything else is BF16:
attention/KDA 11.2 GB, shared experts 2.2 GB, lm_head 1.3 GB, dense MLP 0.9 GB. With
`GLM53_DENSE_FP8=dense,kda` about **11.6 GB of non-expert weights** is read on every step, plus
~4.3 GB of active routed experts per token.

| step shape | bytes (both nodes) | floor |
|---|---:|---:|
| 1 token, no speculative decoding | ~16 GB | ~30 ms → ~33 tok/s max |
| DFlash2 k=7 verify (8 rows, ~58 distinct experts/layer) | ~35–40 GB | ~75–85 ms + ~8 ms drafter + ~3 ms all-reduce |

The measured verify step is 97–101 ms, **~85–95 % of the bandwidth roofline**. Decode on natural
text is limited by draft acceptance (~3.4 tokens/step on prose), not by kernels. Every public
GLM-5.3-Flash drafter (incoai DFlash2, canada-quant DFlash2-G, RedHat DSpark preview) sits at
3.6–3.8 mean acceptance, so no drafter swap gives a step change. Prose ceiling with this drafter ≈ 40–45 tok/s.

## Prefill (8k, one warm prompt, head rank, torch profiler)

| component | time | share |
|---|---:|---:|
| routed MoE (EXL3 fat + thin kernels) | 1.61 s | 32 % (~55 TFLOPS ≈ 60 % of BF16 peak) |
| other BF16 GEMMs (cuBLAS / cutlass / Marlin) | 0.77 s | 15 % |
| NCCL all-reduce | 0.53 s | 10 % (≈ wire speed) |
| mHC hyper-connection kernels | 0.51 s | 10 % (memory-bound by design, ~0.3 s floor) |
| KDA chunk kernels | 0.45 s | 9 % |
| sparse MLA + indexer | 0.32 s | 6 % |
| elementwise / copies | ~0.3 s | 6 % |
| **total** | **~5.05 s** | ideal at BF16 peak ≈ 1.7 s |

There is no single sink left. The realistic headroom from kernel work is about 1.3–1.4× over
this recipe, and each piece costs days of CUDA work. FP8 activations or NVFP4 weights would go
further but change numerics. The kit's KLD panel puts NVFP4 at 2.5× the error of this checkpoint.

## Things that did not help (so you don't have to try them)

- BF16 large-M copies for *all* FP8 projections (KDA o_proj/f_b/g_b, dense MLP): +1–3 % prefill
  for +1.6 GiB/rank, with head low-water down to 2.45 GiB during 128k. Not worth it.
- DFlash2-G / DSpark drafters: acceptance within ~1–4 % of incoai, with 2.3–2.8× the drafter bytes
  read on rank 0 every step.
- `DFLASH_TOKENS=12`, full dense-FP8 groups (`shared,mla`), TP2 drafter: all neutral or worse on
  natural code.
