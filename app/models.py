"""The two local models, pinned to a commit so every install runs the same
weights. One is a third-party ONNX export, and both used to resolve whatever
`main` pointed at on the day of the first boot.

Downloaded once into MODELS_DIR and reused from there; a fresh install with no
network fails loudly here rather than serving without them."""

import logging
import os
import time

from huggingface_hub import snapshot_download

log = logging.getLogger(__name__)

MODELS_DIR = os.environ.get("MODELS_DIR", "/models")
# Half the cores per ONNX session; two sessions may run at once.
THREADS = max(1, (os.cpu_count() or 2) // 2)

TOKENIZER = ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]

# multilingual-e5-small, the official repo, its own ONNX export.
EMBEDDING = (
    "intfloat/multilingual-e5-small",
    "614241f622f53c4eeff9890bdc4f31cfecc418b3",
    ["onnx/model.onnx", "sentencepiece.bpe.model", *TOKENIZER],
)
# bge-reranker-v2-m3 as exported by the onnx-community organisation, int8:
# a quarter of the fp32 size, and it scored the same on our eval set.
RERANKER = (
    "onnx-community/bge-reranker-v2-m3-ONNX",
    "6f5ff65298512715a1e669753bc754d2bc8f367b",
    ["onnx/model_int8.onnx", *TOKENIZER],
)


def local_path(repo, revision, patterns, attempts=5):
    """The snapshot directory for exactly this revision, fetching it if the
    cache does not have it yet. Retries, because the first boot is the one
    time this needs the network and a flaky link must not take five minutes
    of downloading with it."""
    for attempt in range(1, attempts + 1):
        try:
            return snapshot_download(repo, revision=revision, cache_dir=MODELS_DIR, allow_patterns=patterns)
        except Exception as e:  # network, hub, disk: all retried the same way
            if attempt == attempts:
                raise
            wait = min(2**attempt, 60)
            log.warning(
                "model download failed; retrying", extra={"repo": repo, "err": str(e), "wait_s": wait}
            )
            time.sleep(wait)
