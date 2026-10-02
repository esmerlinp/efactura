import hashlib
import json
import os
import re

import requests

from config import Config

TUTORIALS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "tutoriales")
INDEX_PATH = os.path.join(TUTORIALS_DIR, ".index.json")

EMBED_MODEL = "text-embedding-3-small"
EMBED_URL = "https://api.openai.com/v1/embeddings"

_VALID_MODULES = {
    "configuracion", "facturacion", "pos", "inventario",
    "compras", "contabilidad", "finanzas", "rrhh", "gestion",
}


def _norm_abs(path):
    return os.path.abspath(path)


def _iter_tutorial_files():
    if not os.path.isdir(TUTORIALS_DIR):
        return
    for root, dirs, files in os.walk(TUTORIALS_DIR):
        dirs.sort()
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            if fname.startswith("."):
                continue
            yield os.path.join(root, fname)


def _file_content_hash(path):
    with open(path, "r", encoding="utf-8") as fh:
        return hashlib.sha256(fh.read().encode("utf-8")).hexdigest()


def _module_of(path):
    rel = os.path.relpath(path, TUTORIALS_DIR)
    parts = rel.split(os.sep)
    if len(parts) == 1:
        return ""
    return parts[0]


def parse_tutorial(path):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    title = ""
    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break

    return {
        "path": os.path.relpath(path, TUTORIALS_DIR),
        "module": _module_of(path),
        "title": title,
        "content": text,
    }


def chunk_tutorial(doc):
    content = doc["content"]
    heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    matches = list(heading_re.finditer(content))
    chunks = []

    if not matches:
        chunks.append({
            "title": doc["title"],
            "module": doc["module"],
            "heading": "",
            "content": content.strip(),
        })
        return chunks

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if not body:
            continue
        heading = m.group(2).strip()
        chunks.append({
            "title": doc["title"],
            "module": doc["module"],
            "heading": heading,
            "content": body,
        })

    if not chunks:
        chunks.append({
            "title": doc["title"],
            "module": doc["module"],
            "heading": "",
            "content": content.strip(),
        })
    return chunks


def _embed_texts(texts, api_key):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    resp = requests.post(
        EMBED_URL,
        headers=headers,
        json={"model": EMBED_MODEL, "input": texts},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Embeddings API error HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()["data"]
    data.sort(key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class TutorialIndex:
    def __init__(self):
        self.chunks = []
        self._file_hashes = {}

    @classmethod
    def load(cls, api_key=None):
        index = cls()
        index._load_or_build(api_key=api_key)
        return index

    def _load_or_build(self, api_key=None):
        files = list(_iter_tutorial_files())
        if not files:
            return

        current_hashes = {_norm_abs(p): _file_content_hash(p) for p in files}

        cached = None
        if os.path.exists(INDEX_PATH):
            try:
                with open(INDEX_PATH, "r", encoding="utf-8") as fh:
                    cached = json.load(fh)
            except Exception:
                cached = None

        cached_hashes = (cached or {}).get("file_hashes", {})

        stale = cached is None or any(
            current_hashes.get(k) != cached_hashes.get(k)
            for k in current_hashes
        ) or any(
            k not in current_hashes
            for k in cached_hashes
        )

        if not stale:
            self.chunks = cached.get("chunks", [])
            self._file_hashes = cached_hashes
            return

        self._build(files, current_hashes, api_key=api_key)

    def _build(self, files, current_hashes, api_key=None):
        if not api_key:
            api_key = (Config.OPENAI_API_KEY or "").strip()

        docs = [parse_tutorial(p) for p in files]

        pending = []
        for doc in docs:
            pending.extend(chunk_tutorial(doc))

        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            self.chunks = pending
            self._file_hashes = current_hashes
            return

        texts = []
        for c in pending:
            parts = [c["title"] or "", c["heading"] or "", c["content"] or ""]
            texts.append("\n".join(parts))

        vectors = _embed_texts(texts, api_key)
        for c, vec in zip(pending, vectors):
            c["embedding"] = vec

        self.chunks = pending
        self._file_hashes = current_hashes

        self._save()

    def _save(self):
        try:
            payload = {
                "model": EMBED_MODEL,
                "file_hashes": self._file_hashes,
                "chunks": self.chunks,
            }
            with open(INDEX_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ No se pudo guardar el índice de tutoriales: {e}")


_instance = None


def get_tutorial_index(api_key=None):
    global _instance
    if _instance is None:
        _instance = TutorialIndex.load(api_key=api_key)
    return _instance


def search_tutorials(query, module=None, top_k=3, api_key=None):
    index = get_tutorial_index(api_key=api_key)
    if not index.chunks:
        return {"results": [], "message": "No hay tutoriales disponibles."}

    q_embedding = None
    if api_key and any("embedding" in c for c in index.chunks):
        try:
            q_embedding = _embed_texts([query], api_key)[0]
        except Exception:
            q_embedding = None

    scored = []
    for c in index.chunks:
        if module:
            mod = (c.get("module") or "").lower()
            if mod != module.lower():
                continue
        if q_embedding and "embedding" in c:
            score = _cosine(q_embedding, c["embedding"])
        else:
            score = _keyword_score(query, c)

        scored.append((score, c))

    scored.sort(key=lambda t: t[0], reverse=True)

    results = []
    seen = set()
    for score, c in scored:
        if score <= 0:
            continue
        key = (c["title"], c["heading"])
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "titulo": c["title"],
            "modulo": c["module"],
            "seccion": c["heading"],
            "contenido": c["content"],
            "relevancia": round(float(score), 4),
        })
        if len(results) >= top_k:
            break

    return {"results": results}


def _keyword_score(query, chunk):
    text = " ".join([
        chunk.get("title") or "",
        chunk.get("heading") or "",
        chunk.get("content") or "",
    ]).lower()
    tokens = _tokenize(query)
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in text)
    return hits / len(tokens)


def _tokenize(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9áéíóúñü\s]", " ", text)
    tokens = [t for t in text.split() if len(t) > 2]
    return tokens
