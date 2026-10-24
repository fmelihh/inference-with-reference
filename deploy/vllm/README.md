# vLLM deployment

How the drafting model is served. The application does not use these scripts; they document the setup so it can be reproduced on any single-GPU Linux server with Docker and the NVIDIA container toolkit.

Private, machine-specific notes (addresses, users, other services on the box) go in `SERVER.local.md`, which is git-ignored.

## Files

- [`serve.sh`](serve.sh): starts the `vllm-iwr` container. Everything is set with environment variables (`MODEL`, `SPEC_METHOD`, `GPU_UTIL`, `PORT`, `BIND_ADDR`, `HF_CACHE`, ...).
- [`verify.sh`](verify.sh): smoke test. Sends one whole-document edit and prints tokens/s plus speculative-decoding counters.

## Deploy

```bash
# on the GPU server
./serve.sh && docker logs -f vllm-iwr
```

`BIND_ADDR` defaults to `127.0.0.1`. To serve the app from another machine, set it to an address on a private network the app can reach. Do not expose the API on a public interface: it has no authentication.

Smoke test, from any machine that can reach the server:

```bash
BASE=http://<vllm-server>:8001 ./deploy/vllm/verify.sh
```

The first request after a start is slow (one-time compilation and warm-up); judge speed from the second run.

## GPU budget

`--gpu-memory-utilization` is a share of the *whole* GPU, so the values of all vLLM containers on one card must add up to less than about 0.95. `serve.sh` defaults to 0.30.

## Inference with reference in vLLM

vLLM implements reference-based drafting as speculative decoding methods that need no draft model:

- `ngram` (default here): matches the last `prompt_lookup_min`..`prompt_lookup_max` generated tokens against the prompt and proposes the next `num_speculative_tokens` tokens that followed in the prompt. With the document in the prompt, this is LLMA / prompt-lookup decoding.
- `suffix`: suffix-tree matching over the prompt and earlier outputs. Worth comparing with `ngram`.
- `off`: baseline for benchmarks.

Speculation is lossless in exact arithmetic; in practice bf16 batched kernels are not bit-reproducible, so long greedy outputs can occasionally differ from the baseline. It does not reduce the number of output tokens; it reduces the number of sequential forward passes, so latency and GPU time per request go down.

Acceptance can be read from `/metrics`: `vllm:spec_decode_num_accepted_tokens_total / vllm:spec_decode_num_draft_tokens_total`.

## Model notes

- Default: `mistralai/Ministral-3-8B-Instruct-2512`, a standard-attention model, which is the simplest case for speculative decoding.
- Alternative: `Qwen/Qwen3.5-9B` (`MODEL=Qwen/Qwen3.5-9B ./serve.sh`). It mixes full and linear attention layers; speculation support should be benchmarked before relying on it. `serve.sh` turns thinking off (`enable_thinking: false`) because edits need direct output.
