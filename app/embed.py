from functools import cache

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

MODEL = "intfloat/multilingual-e5-small"

# fastembed ships only the large e5 variant. The small one has an official ONNX
# export in the same HF repo, so we register it instead of taking a different model.
TextEmbedding.add_custom_model(
    MODEL, pooling=PoolingType.MEAN, normalization=True, sources=ModelSource(hf=MODEL), dim=384
)


@cache
def _model():
    # Lazy so importing this module in tests does not download 120 MB.
    return TextEmbedding(MODEL, cache_dir="/models")


def warm():
    _model()


# e5 models are trained with these prefixes; recall drops measurably without them.
def passages(texts):
    return [v.tolist() for v in _model().embed([f"passage: {t}" for t in texts])]


def query(text):
    return next(_model().embed([f"query: {text}"])).tolist()


def literal(vec):
    # pgvector's text input format; psycopg has no native adapter without the
    # pgvector package, and this is all that package would do for us.
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
