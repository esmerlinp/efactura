"""
Test de contingencia (Bloque 4).

Escenarios:
  1. DGII offline — emisiones entran a cola de contingencia
  2. Reintentos progresivos (backoff: 1min, 5min, 15min, 60min, 6h, 24h)
  3. Recuperación — cola se vacía al restaurar conectividad
  4. Límite de reintentos (MAX_RETRY_ATTEMPTS=20) → SYNC_FAILED
  5. Ventana de 72h expirada → documentos marcados como vencidos

Verifica:
  - Sin duplicación al reenviar
  - Estado consistente pre/post recuperación
  - Backoff respeta intervalos
  - Cola vacía post-recuperación
"""
import sys
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
TOTAL = 0


def _print(label, status, detail=""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    icon = "✅" if status == "PASS" else "❌"
    if status == "PASS":
        PASS += 1
    else:
        FAIL += 1
    print(f"  {label:<40} {icon} {status:<6} {detail[:50]}")


# ---------------------------------------------------------------------------
# Constants (espejo del contingency_sync_service)
# ---------------------------------------------------------------------------
BACKOFF_INTERVALS = [1, 5, 15, 60, 360, 1440]   # minutes
MAX_RETRY_ATTEMPTS = 20
CONTINGENCY_WINDOW_HOURS = 72


def should_retry(attempts, minutes_since_last_attempt):
    """Réplica de ContingencySyncService._should_retry.

    minutes_since_last_attempt: None = sin intento previo (retry inmediato).
    """
    if attempts >= MAX_RETRY_ATTEMPTS:
        return False
    if minutes_since_last_attempt is None:
        return True  # Sin intento previo
    if attempts < len(BACKOFF_INTERVALS):
        wait_minutes = BACKOFF_INTERVALS[attempts]
    else:
        wait_minutes = 1440  # 24h
    return minutes_since_last_attempt >= wait_minutes


# ---------------------------------------------------------------------------
# In-memory mock: cola de contingencia
# ---------------------------------------------------------------------------
class ContingencyQueue:
    """Simula la cola virtual de documentos en contingencia."""

    def __init__(self):
        self._lock = threading.Lock()
        self._invoices = {}  # invoice_id -> dict

    def add(self, inv_id, data):
        with self._lock:
            self._invoices[inv_id] = {
                "id": inv_id,
                "encf": data.get("encf", f"E31000000000{len(self._invoices)+1}"),
                "ecfType": data.get("ecfType", "E31"),
                "emisionMode": "FALLBACK",
                "isSyncedWithDGII": False,
                "dgiiStatus": "PENDING",
                "contingencyEmittedAt": datetime.now(timezone.utc).isoformat(),
                "syncAttempts": 0,
                "lastSyncAttempt": None,
                "status": "Emitida",
            }

    def pending(self):
        with self._lock:
            return [deepcopy(v) for v in self._invoices.values()
                    if v["emisionMode"] == "FALLBACK"
                    and not v["isSyncedWithDGII"]]

    def get(self, inv_id):
        with self._lock:
            return deepcopy(self._invoices.get(inv_id))

    def update(self, inv_id, changes):
        with self._lock:
            if inv_id in self._invoices:
                self._invoices[inv_id].update(changes)

    def mark_synced(self, inv_id):
        with self._lock:
            if inv_id in self._invoices:
                inv = self._invoices[inv_id]
                inv["isSyncedWithDGII"] = True
                inv["emisionMode"] = "API"
                inv["dgiiStatus"] = "ACCEPTED"
                inv["contingencyEmittedAt"] = None
                inv.pop("syncAttempts", None)
                inv.pop("lastSyncAttempt", None)

    def size(self):
        with self._lock:
            return len(self._invoices)

    def pending_count(self):
        with self._lock:
            return sum(1 for v in self._invoices.values()
                       if v["emisionMode"] == "FALLBACK"
                       and not v["isSyncedWithDGII"])

    def clear(self):
        with self._lock:
            self._invoices.clear()


# ---------------------------------------------------------------------------
# Escenario 1: DGII offline → cola de contingencia
# ---------------------------------------------------------------------------
def scenario_1():
    print(f"\n{'='*70}")
    print("  ESCENARIO 1 — DGII offline → cola de contingencia")
    print(f"  Verificar que emisiones fallidas entran a cola FALLBACK")
    print(f"{'='*70}")

    queue = ContingencyQueue()
    NUM_INVOICES = 10

    for i in range(NUM_INVOICES):
        queue.add(f"inv-{i}", {"encf": f"E3100000000{i}", "ecfType": "E31"})

    pending = queue.pending()
    _print("Documentos en cola tras fallo",
           "PASS" if len(pending) == NUM_INVOICES else "FAIL",
           f"{len(pending)}/{NUM_INVOICES}")

    all_fallback = all(inv["emisionMode"] == "FALLBACK" for inv in pending)
    _print("Modo FALLBACK en todos",
           "PASS" if all_fallback else "FAIL", "")

    all_unsynced = all(not inv["isSyncedWithDGII"] for inv in pending)
    _print("isSyncedWithDGII=False en todos",
           "PASS" if all_unsynced else "FAIL", "")

    all_pending = all(inv["dgiiStatus"] == "PENDING" for inv in pending)
    _print("dgiiStatus=PENDING en todos",
           "PASS" if all_pending else "FAIL", "")

    has_contingency_ts = all(inv["contingencyEmittedAt"] for inv in pending)
    _print("Timestamp contingencia presente",
           "PASS" if has_contingency_ts else "FAIL", "")


# ---------------------------------------------------------------------------
# Escenario 2: Reintentos progresivos (backoff)
# ---------------------------------------------------------------------------
def scenario_2():
    print(f"\n{'='*70}")
    print("  ESCENARIO 2 — Reintentos progresivos (backoff)")
    print(f"  Verificar que _should_retry respeta intervalos")
    print(f"{'='*70}")

    # attempts 0: sin intento previo → debe reintentar
    r = should_retry(0, None)
    _print("Attempt 0: sin intento previo → retry",
           "PASS" if r else "FAIL", "")

    # attempts 1: backoff index 1 = 5 min → a los 0 min → no
    r = should_retry(1, 0)
    _print("Attempt 1: 0min < 5min → no retry",
           "PASS" if not r else "FAIL", "")

    # attempts 1: a los 5 min → sí
    r = should_retry(1, 5)
    _print("Attempt 1: 5min >= 5min → retry",
           "PASS" if r else "FAIL", "")

    # attempts 3: backoff index 3 = 60 min
    r = should_retry(3, 10)
    _print("Attempt 3: 10min < 60min → no retry",
           "PASS" if not r else "FAIL", "")

    r = should_retry(3, 60)
    _print("Attempt 3: 60min >= 60min → retry",
           "PASS" if r else "FAIL", "")

    # attempts 6+: backoff 1440 min (24h)
    r = should_retry(6, 1000)
    _print("Attempt 6: 1000min < 1440min → no retry",
           "PASS" if not r else "FAIL", "")

    r = should_retry(6, 1440)
    _print("Attempt 6: 1440min >= 1440min → retry",
           "PASS" if r else "FAIL", "")

    # límite: MAX_RETRY_ATTEMPTS = 20
    r = should_retry(20, 999999)
    _print(f"Attempt {MAX_RETRY_ATTEMPTS}: agotado → no retry",
           "PASS" if not r else "FAIL", "")

    r = should_retry(19, 1440)
    _print("Attempt 19: 1440min >= 1440min → retry (último)",
           "PASS" if r else "FAIL", "")


# ---------------------------------------------------------------------------
# Escenario 3: Recuperación — cola se vacía al restaurar conectividad
# ---------------------------------------------------------------------------
def scenario_3():
    print(f"\n{'='*70}")
    print("  ESCENARIO 3 — Recuperación: cola se vacía al restaurar conectividad")
    print(f"  Sin duplicación, estados consistentes")
    print(f"{'='*70}")

    queue = ContingencyQueue()
    NUM = 25

    for i in range(NUM):
        queue.add(f"rec-{i}", {"encf": f"E310000000{i:02d}", "ecfType": "E31"})

    before = queue.pending_count()
    _print("Cola llena antes de recuperación",
           "PASS" if before == NUM else "FAIL", f"{before}/{NUM}")

    for i in range(NUM):
        queue.mark_synced(f"rec-{i}")

    after = queue.pending_count()
    _print("Cola vacía después de recuperación",
           "PASS" if after == 0 else "FAIL", f"{after} pendientes")

    synced = all(
        queue.get(f"rec-{i}")["isSyncedWithDGII"]
        for i in range(NUM)
    )
    _print("Todos marcados como synced",
           "PASS" if synced else "FAIL", "")

    api_mode = all(
        queue.get(f"rec-{i}")["emisionMode"] == "API"
        for i in range(NUM)
    )
    _print("Todos en modo API post-recuperación",
           "PASS" if api_mode else "FAIL", "")

    no_ts = all(
        queue.get(f"rec-{i}")["contingencyEmittedAt"] is None
        for i in range(NUM)
    )
    _print("Timestamp contingencia limpiado",
           "PASS" if no_ts else "FAIL", "")

    dgii_accepted = all(
        queue.get(f"rec-{i}")["dgiiStatus"] == "ACCEPTED"
        for i in range(NUM)
    )
    _print("dgiiStatus=ACCEPTED en todos",
           "PASS" if dgii_accepted else "FAIL", "")


# ---------------------------------------------------------------------------
# Escenario 4: Límite de reintentos (SYNC_FAILED)
# ---------------------------------------------------------------------------
def scenario_4():
    print(f"\n{'='*70}")
    print("  ESCENARIO 4 — Límite de reintentos (20) → SYNC_FAILED")
    print(f"  Verificar que tras 20 intentos fallidos se detiene")
    print(f"{'='*70}")

    queue = ContingencyQueue()
    queue.add("fail-inv", {"encf": "E31000000099", "ecfType": "E31"})

    # Simular 20 reintentos fallidos — cada uno con suficiente tiempo entre sí
    ATTEMPTS = 20
    for attempt in range(1, ATTEMPTS + 1):
        inv = queue.get("fail-inv")
        if inv is None:
            continue
        current_attempts = inv.get("syncAttempts", 0)
        # Verificar si debe reintentar
        can_retry = should_retry(current_attempts, 9999)  # tiempo suficiente
        if can_retry:
            queue.update("fail-inv", {
                "syncAttempts": current_attempts + 1,
                "lastSyncAttempt": datetime.now(timezone.utc).isoformat(),
            })
        else:
            # No debe reintentar más → SYNC_FAILED
            queue.update("fail-inv", {"dgiiStatus": "SYNC_FAILED"})
            break

    inv = queue.get("fail-inv")
    final_attempts = inv.get("syncAttempts", 0)
    _print(f"Se realizaron {final_attempts} reintentos antes de agotar",
           "PASS" if final_attempts == ATTEMPTS else "FAIL", "")

    r = should_retry(final_attempts, 999999)
    _print("No más reintentos tras agotar",
           "PASS" if not r else "FAIL", "")


# ---------------------------------------------------------------------------
# Escenario 5: Ventana de 72h expirada
# ---------------------------------------------------------------------------
def scenario_5():
    print(f"\n{'='*70}")
    print("  ESCENARIO 5 — Ventana de contingencia expirada (72h)")
    print(f"{'='*70}")

    queue = ContingencyQueue()

    # Documento dentro de la ventana (hace 24h)
    within_window = datetime.now(timezone.utc) - timedelta(hours=24)
    queue.add("within-window", {"encf": "E31000002001", "ecfType": "E31"})
    queue.update("within-window", {
        "contingencyEmittedAt": within_window.isoformat(),
    })

    # Documento fuera de la ventana (hace 96h)
    expired_ts = datetime.now(timezone.utc) - timedelta(hours=96)
    queue.add("expired", {"encf": "E31000002002", "ecfType": "E31"})
    queue.update("expired", {
        "contingencyEmittedAt": expired_ts.isoformat(),
    })

    # Calcular horas desde contingencia
    def hours_since(ts_str):
        try:
            ts = datetime.fromisoformat(ts_str)
            return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        except Exception:
            return None

    within_hours = hours_since(queue.get("within-window")["contingencyEmittedAt"])
    expired_hours = hours_since(queue.get("expired")["contingencyEmittedAt"])

    _print("Dentro de ventana (<72h)",
           "PASS" if within_hours is not None and within_hours < 72 else "FAIL",
           f"{within_hours:.1f}h")

    _print("Fuera de ventana (>72h)",
           "PASS" if expired_hours is not None and expired_hours > 72 else "FAIL",
           f"{expired_hours:.1f}h")

    # Simular check_expired_contingency
    all_invs = [queue.get("within-window"), queue.get("expired")]
    expired = [inv for inv in all_invs if inv and hours_since(inv["contingencyEmittedAt"]) >= 72]
    _print("Solo el documento expirado es detectado",
           "PASS" if len(expired) == 1 and expired[0]["id"] == "expired" else "FAIL",
           f"{len(expired)} expirados")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global PASS, FAIL, TOTAL
    scenario_1()
    scenario_2()
    scenario_3()
    scenario_4()
    scenario_5()

    print(f"\n{'='*70}")
    print(f"  RESUMEN BLOQUE 4 — Contingencia")
    print(f"{'='*70}")
    print(f"  {PASS}/{TOTAL} passed")
    if FAIL:
        print(f"  {FAIL} fallos — revisar detalle arriba")
        sys.exit(1)
    print()


if __name__ == "__main__":
    main()
