from functools import cache

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

import models

MODEL = models.EMBEDDING[0]

# fastembed ships only the large e5 variant. The small one has an official ONNX
# export in the same HF repo, so we register it instead of taking a different model.
TextEmbedding.add_custom_model(
    MODEL, pooling=PoolingType.MEAN, normalization=True, sources=ModelSource(hf=MODEL), dim=384
)


@cache
def _model():
    # Lazy so importing this module in tests does not download the model.
    return TextEmbedding(
        MODEL, specific_model_path=models.local_path(*models.EMBEDDING), threads=models.THREADS
    )


def warm():
    _model()


# e5 models are trained with these prefixes; recall drops measurably without them.
def passages(texts):
    return [v.tolist() for v in _model().embed([f"passage: {t}" for t in texts])]


def query(text):
    return next(_model().embed([f"query: {text}"])).tolist()


def passage_literal(text):
    """The one shape callers need: embed a passage, ready for pgvector."""
    return literal(passages([text])[0])


def literal(vec):
    # pgvector's text input format; psycopg has no native adapter without the
    # pgvector package, and this is all that package would do for us.
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
