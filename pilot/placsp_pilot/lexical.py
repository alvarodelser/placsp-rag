"""Keyword vectors for the pilot's hybrid search: BM25 as a Qdrant sparse vector.

Qdrant applies the IDF (the collection's `bm25` sparse vector has modifier=IDF); this module
gives each chunk its term weights with BM25's saturation and length norm, and each query its
terms with weight 1. Spanish text: lower case, accents folded, stop words out, a light stemmer
that folds plural and gender ("contratos" = "contrato", "obligadas" = "obligado") and keeps
numbers and ordinals ("8ª" -> "8a", "2024"), which is what keyword search is for here.

The same file is pilot/placsp_pilot/lexical.py (the indexer) and search-api/pilot_lexical.py
(the queries): a pilot test checks they are identical.
"""
import re
import unicodedata
import zlib
from collections import Counter

K1, B = 1.2, 0.75

STOP = set("""
a al algo algun alguna algunas alguno algunos ante antes asi aun aunque bajo cada como con contra cual cuales
cuando de del desde donde dos e el ella ellas ello ellos en entre era es esa esas ese eso esos esta estan estas
este esto estos fue fueron ha han hasta hay la las le les lo los mas me mi mientras muy ni no nos o os otra
otras otro otros para pero por porque que quien quienes se sea sean segun ser si sido sin sobre son su sus
tal tambien tanto te tiene tienen todo todos tras tu u un una unas uno unos y ya
""".split())

_TOKEN = re.compile(r"[a-z0-9]+")


def fold(text: str) -> str:
    text = text.replace("ª", "a").replace("º", "o")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def stem(w: str) -> str:
    if w.isdigit() or len(w) <= 4:
        return w
    if w.endswith("es") and len(w) > 5 and w[-3] not in "aeiou":
        w = w[:-2]
    elif w.endswith("s"):
        w = w[:-1]
    if len(w) > 5 and w[-1] in "ao":
        w = w[:-1]
    return w


def terms(text: str) -> list[str]:
    return [stem(t) for t in _TOKEN.findall(fold(text)) if t not in STOP and (len(t) > 1 or t.isdigit())]


def index_of(term: str) -> int:
    return zlib.crc32(term.encode()) & 0x7FFFFFFF


def _sparse(weights: dict[int, float]) -> tuple[list[int], list[float]]:
    items = sorted(weights.items())
    return [i for i, _ in items], [w for _, w in items]


def doc_vector(text: str, avg_len: float) -> tuple[list[int], list[float]]:
    """A chunk's BM25 term weights (without the IDF, which Qdrant applies)."""
    ts = terms(text)
    n = len(ts) or 1
    tf = Counter(index_of(t) for t in ts)
    norm = K1 * (1 - B + B * n / (avg_len or n))
    return _sparse({i: c * (K1 + 1) / (c + norm) for i, c in tf.items()})


def query_vector(text: str) -> tuple[list[int], list[float]]:
    return _sparse({index_of(t): 1.0 for t in set(terms(text))})
