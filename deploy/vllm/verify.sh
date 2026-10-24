#!/usr/bin/env bash
#
# Smoke test for the drafting model: lists models, runs one edit request and
# reports speed and speculative-decoding acceptance from /metrics.
#
# Usage: BASE=http://<vllm-server>:8001 ./verify.sh
#
set -u
BASE="${BASE:?set BASE, e.g. http://<vllm-server>:8001}"
MODEL="${MODEL:-drafting}"

echo "=== models ==="
curl -s "$BASE/v1/models" | python3 -c "import json,sys; print([m['id'] for m in json.load(sys.stdin)['data']])"

echo "=== edit request (whole document returned, one sentence changed) ==="
BASE="$BASE" MODEL="$MODEL" python3 - <<'PY'
import json, os, time, urllib.request

doc = "\n".join(
    f"{i}. The quarterly report shows that revenue in region {i} grew steadily "
    f"while operating costs remained stable throughout the period."
    for i in range(1, 31)
)
prompt = (
    "Return the full document below unchanged, except rewrite line 7 to be shorter.\n"
    "Output only the document.\n\n" + doc
)
req = urllib.request.Request(
    os.environ["BASE"] + "/v1/chat/completions",
    data=json.dumps({
        "model": os.environ["MODEL"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0,
    }).encode(),
    headers={"Content-Type": "application/json"},
)
t = time.time()
d = json.load(urllib.request.urlopen(req, timeout=300))
el = time.time() - t
ct = d["usage"]["completion_tokens"]
print(f"  {ct} tokens / {el:.2f} s = {ct / el:.1f} tok/s")
print("  line 7:", d["choices"][0]["message"]["content"].splitlines()[6][:160])
PY

echo "=== speculative decoding counters ==="
curl -s "$BASE/metrics" | grep -E "^vllm:spec_decode_num_(draft|accepted|emitted)_tokens_total" || echo "  (no counters: speculation is off or /metrics is unreachable)"
