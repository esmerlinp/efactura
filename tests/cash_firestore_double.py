"""Doble en memoria de Firestore para pruebas de concurrencia del módulo de caja.

Imita las primitivas atómicas que usa el código de producción (db_service.py):

  - ``DocumentReference.create()`` falla si el documento ya existe (``AlreadyExistsError``).
  - ``db.transaction()`` + ``@transactional`` con control de concurrencia optimista:
    detección de conflicto de escritura sobre las lecturas y reintento automático.

No sustituye al emulador de Firestore, pero permite probar la lógica de guardas de
nuestro código (ocupación de caja, bloqueo de venta vs cierre, idempotencia con
lease) bajo condiciones concurrentes deterministas.
"""
from __future__ import annotations

import itertools
import threading
from collections import defaultdict


class AlreadyExistsError(Exception):
    pass


class Conflict(Exception):
    pass


class FieldFilter:
    def __init__(self, field, op, value):
        self.field = field
        self.op = op
        self.value = value

    def matches(self, data):
        actual = data.get(self.field)
        if self.op in ("==", "="):
            return actual == self.value
        if self.op == "in":
            return actual in (self.value or [])
        return False


class Snapshot:
    def __init__(self, exists, data, ref):
        self._exists = exists
        self._data = data
        self._ref = ref

    @property
    def exists(self):
        return self._exists

    @property
    def id(self):
        return self._ref.doc_id if self._ref is not None else None

    @property
    def reference(self):
        return self._ref

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Store:
    """Almacén en memoria particionado por (company_id, coll_name, doc_id)."""

    def __init__(self):
        self._docs = {}          # (cid, coll, doc) -> data
        self._version = defaultdict(int)  # (cid, coll, doc) -> version
        self._coll_ids = defaultdict(lambda: itertools.count())
        self._lock = threading.RLock()
        # Hook para inyectar una escritura concurrente justo antes del
        # conflict-check de commit (permite probar el reintento de forma
        # determinista en las pruebas de concurrencia).
        self.before_commit_hook = None

    # --- API estilo firebase_admin.firestore ---
    def collection(self, company_id, coll_name):
        return Collection(self, company_id, coll_name)

    def transaction(self):
        return Transaction(self)

    @staticmethod
    def transactional(fn):
        def wrapper(transaction, max_retries=5):
            last = None
            for _ in range(max_retries):
                try:
                    result = fn(transaction)
                    transaction.commit()
                    return result
                except Conflict as e:
                    last = e
                    transaction.reset()
            if last:
                raise last
            return None
        return wrapper


class Collection:
    def __init__(self, store, company_id, coll_name):
        self.store = store
        self.company_id = company_id
        self.coll_name = coll_name

    def document(self, doc_id):
        return DocRef(self.store, self.company_id, self.coll_name, doc_id)

    def get(self):
        return Query(self.store, self.company_id, self.coll_name, None).get()

    def where(self, filter_=None, **kwargs):
        # Acepta tanto `where(filter=...)` como `where(...)` posicional usado por el
        # código real: `coll.where(filter=firestore.FieldFilter(...))`.
        flt = kwargs.get("filter", filter_)
        return Query(self.store, self.company_id, self.coll_name, flt)


class Query:
    def __init__(self, store, company_id, coll_name, flt):
        self.store = store
        self.company_id = company_id
        self.coll_name = coll_name
        self.flt = flt

    def get(self):
        results = []
        for (cid, coll, doc), data in list(self.store._docs.items()):
            if cid != self.company_id or coll != self.coll_name:
                continue
            if self.flt is not None and not self.flt.matches(data):
                continue
            results.append(Snapshot(True, data, DocRef(self.store, cid, coll, doc)))
        return results


class DocRef:
    def __init__(self, store, company_id, coll_name, doc_id):
        self.store = store
        self.company_id = company_id
        self.coll_name = coll_name
        self.doc_id = doc_id

    @property
    def _key(self):
        return (self.company_id, self.coll_name, self.doc_id)

    def get(self, transaction=None):
        if transaction is not None:
            return transaction.get(self)
        exists = self._key in self.store._docs
        data = self.store._docs.get(self._key)
        return Snapshot(exists, data, self)

    def create(self, data):
        with self.store._lock:
            if self._key in self.store._docs:
                raise AlreadyExistsError(f"Documento {self.doc_id} ya existe")
            self.store._docs[self._key] = dict(data)
            self.store._version[self._key] += 1

    def set(self, data):
        with self.store._lock:
            self.store._docs[self._key] = dict(data)
            self.store._version[self._key] += 1

    def update(self, data):
        with self.store._lock:
            if self._key not in self.store._docs:
                raise AlreadyExistsError(f"Documento {self.doc_id} no existe para update")
            merged = dict(self.store._docs[self._key])
            merged.update(data)
            self.store._docs[self._key] = merged
            self.store._version[self._key] += 1

    def delete(self):
        with self.store._lock:
            self.store._docs.pop(self._key, None)
            self.store._version[self._key] += 1


class Transaction:
    def __init__(self, store):
        self.store = store
        self._reads = {}   # key -> version at read time
        self._writes = {}  # key -> ("set", data) | ("update", data) | ("delete", None)

    def reset(self):
        self._reads.clear()
        self._writes.clear()

    def _read(self, ref):
        key = ref._key
        # Si hay escritura pendiente sobre el mismo doc, devolver el buffer.
        if key in self._writes:
            kind, data = self._writes[key]
            if kind == "delete":
                return Snapshot(False, None, ref)
            return Snapshot(True, data, ref)
        exists = key in self.store._docs
        data = self.store._docs.get(key)
        self._reads.setdefault(key, self.store._version.get(key, 0))
        return Snapshot(exists, data, ref)

    def get(self, ref):
        return self._read(ref)

    def create(self, ref, data):
        key = ref._key
        if key in self.store._docs:
            raise AlreadyExistsError(f"Documento {ref.doc_id} ya existe")
        self._writes[key] = ("set", dict(data))

    def set(self, ref, data):
        self._writes[ref._key] = ("set", dict(data))

    def update(self, ref, data):
        snap = self._read(ref)
        if not snap.exists:
            raise AlreadyExistsError(f"Documento {ref.doc_id} no existe para update")
        merged = dict(snap.to_dict())
        merged.update(data)
        self._writes[ref._key] = ("set", merged)

    def delete(self, ref):
        self._writes[ref._key] = ("delete", None)

    def commit(self):
        with self.store._lock:
            hook = getattr(self.store, "before_commit_hook", None)
            if hook is not None:
                hook(self.store)
            # Verificación de concurrencia optimista: ninguna lectura pudo cambiar.
            for key, ver in self._reads.items():
                if self.store._version.get(key, 0) != ver:
                    raise Conflict(f"Conflicto de escritura en {key}")
            for key, (kind, data) in self._writes.items():
                if kind == "delete":
                    self.store._docs.pop(key, None)
                else:
                    self.store._docs[key] = data
                self.store._version[key] += 1
            self._reads.clear()
            self._writes.clear()
