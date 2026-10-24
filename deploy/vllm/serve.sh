#!/usr/bin/env bash
#
# Start the drafting model on the GPU server as a standalone vLLM container.
#
# Reference-based speculative decoding ("inference with reference") is on by
# default: vLLM drafts tokens by copying n-grams from the prompt (the document)
# and verifies them in one forward pass. Output is identical to plain decoding.
#
# Usage (run on the server):
#   ./serve.sh                       # default model, ngram speculation
#   SPEC_METHOD=off ./serve.sh       # baseline without speculation
#   SPEC_METHOD=suffix ./serve.sh    # suffix decoding (also reference-based)
#   MODEL=Qwen/Qwen3.5-9B ./serve.sh   # alternative model
#
set -euo pipefail

NAME="${NAME:-vllm-iwr}"
IMAGE="${IMAGE:-vllm/vllm-openai:v0.28.0}"
MODEL="${MODEL:-mistralai/Ministral-3-8B-Instruct-2512}"
SERVED_NAME="${SERVED_NAME:-drafting}"
PORT="${PORT:-8001}"
BIND_ADDR="${BIND_ADDR:-127.0.0.1}"               # set to a private interface to serve other machines; never a public one
GPU_UTIL="${GPU_UTIL:-0.30}"                       # share of the whole GPU; leave room for other services
MAX_LEN="${MAX_LEN:-32768}"
MAX_SEQS="${MAX_SEQS:-32}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
VLLM_CACHE="${VLLM_CACHE:-$HOME/.cache/vllm}"

SPEC_METHOD="${SPEC_METHOD:-ngram}"                # ngram | suffix | off
SPEC_TOKENS="${SPEC_TOKENS:-8}"                    # max tokens drafted per step
LOOKUP_MAX="${LOOKUP_MAX:-4}"                      # longest n-gram matched in the prompt
LOOKUP_MIN="${LOOKUP_MIN:-2}"                      # shortest n-gram matched in the prompt

case "$SPEC_METHOD" in
  ngram)  SPEC_ARGS=(--speculative-config "{\"method\":\"ngram\",\"num_speculative_tokens\":$SPEC_TOKENS,\"prompt_lookup_max\":$LOOKUP_MAX,\"prompt_lookup_min\":$LOOKUP_MIN}") ;;
  suffix) SPEC_ARGS=(--speculative-config "{\"method\":\"suffix\",\"num_speculative_tokens\":$SPEC_TOKENS}") ;;
  off)    SPEC_ARGS=() ;;
  *) echo "unknown SPEC_METHOD: $SPEC_METHOD (ngram|suffix|off)" >&2; exit 1 ;;
esac

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" \
  --restart unless-stopped --gpus all --ipc=host \
  -p "${BIND_ADDR}:${PORT}:8000" \
  -v "$HF_CACHE":/root/.cache/huggingface \
  -v "$VLLM_CACHE":/root/.cache/vllm \
  -e PYTHONUNBUFFERED=1 \
  "$IMAGE" \
    "$MODEL" \
    --served-model-name "$SERVED_NAME" \
    --gpu-memory-utilization "$GPU_UTIL" \
    --max-model-len "$MAX_LEN" \
    --max-num-seqs "$MAX_SEQS" \
    --language-model-only \
    --enable-prefix-caching \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
    "${SPEC_ARGS[@]}" \
    --port 8000

echo "started: $NAME  model=$MODEL  spec=$SPEC_METHOD  url=http://${BIND_ADDR}:${PORT}/v1"
echo "logs:    docker logs -f $NAME"
