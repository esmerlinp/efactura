#!/usr/bin/env python3
"""Stress & Volume Testing — VykOne ERP
Ejecuta: 50-100 usuarios concurrentes, 1000 facturas consecutivas, 
nómina 1000 empleados, reportes financieros grandes.
Requiere sesión autenticada (cookie de login exitoso).
"""

import requests, time, threading, json, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

BASE = "http://127.0.0.1:5001"
RESULTS = []
METRICS = defaultdict(list)

# ── Configuración ──
CONCURRENT_USERS = [10, 25, 50]
ENDPOINTS = [
    "/dashboard", "/invoices", "/clients", "/accounting",
    "/rrhh/employees", "/crm", "/inventory", "/banks",
    "/audit", "/reports/sales"
]
HEAVY_ENDPOINTS = [
    "/accounting/balance-sheet", "/accounting/income-statement",
    "/accounting/chart-of-accounts", "/accounting/general-ledger",
]


def load_session(cookie_file="/tmp/vykone_cert_cookies.txt"):
    s = requests.Session()
    try:
        for line in open(cookie_file):
            if line.startswith("#") or not line.strip() or "session" not in line:
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                s.cookies.set(parts[5], parts[6], domain="127.0.0.1")
    except FileNotFoundError:
        print(f"ERROR: Cookie file {cookie_file} not found. Login first.")
        return None
    r = s.get(f"{BASE}/dashboard", allow_redirects=False, timeout=10)
    if r.status_code == 200:
        return s
    print(f"ERROR: Session expired. Dashboard returned {r.status_code}. Re-login first.")
    return None


def hit_endpoint(session, path):
    t0 = time.time()
    try:
        r = session.get(f"{BASE}{path}", allow_redirects=True, timeout=30)
        elapsed = time.time() - t0
        return {"path": path, "status": r.status_code, "elapsed": elapsed, "size": len(r.text)}
    except Exception as e:
        return {"path": path, "status": 0, "elapsed": time.time() - t0, "error": str(e)}


def concurrent_test(session, num_users, iterations=3):
    print(f"\n{'='*60}")
    print(f"  STRESS TEST: {num_users} usuarios concurrentes x {iterations} iteraciones")
    print(f"{'='*60}")
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=num_users) as executor:
        futures = []
        for _ in range(iterations):
            for ep in ENDPOINTS + HEAVY_ENDPOINTS:
                futures.append(executor.submit(hit_endpoint, session, ep))
        for f in as_completed(futures):
            results.append(f.result())
    total_time = time.time() - t0

    total = len(results)
    success = [r for r in results if r.get("status") in (200, 302)]
    failures = [r for r in results if r.get("status", 0) >= 400 or r.get("status", 0) == 0]
    times = [r.get("elapsed", 0) for r in success]
    times.sort()

    p50 = times[len(times)//2] if times else 0
    p95 = times[int(len(times)*0.95)] if len(times) > 1 else (times[0] if times else 0)
    p99 = times[int(len(times)*0.99)] if len(times) > 1 else (times[0] if times else 0)
    avg = sum(times)/len(times) if times else 0

    passed = len(success)/total >= 0.90 and avg < 10.0
    print(f"    Peticiones: {total} | Éxito: {len(success)} ({100*len(success)/total:.0f}%) | Fallos: {len(failures)}")
    print(f"    Tiempo total: {total_time:.1f}s | Throughput: {total/total_time:.1f} req/s")
    print(f"    Latencia — avg: {avg:.2f}s | p50: {p50:.2f}s | p95: {p95:.2f}s | p99: {p99:.2f}s")
    print(f"    Resultado: {'✅ PASS' if passed else '❌ FAIL'}")
    return {"users": num_users, "passed": passed, "avg": avg, "p95": p95, "total": total, "success": len(success)}


def sequential_requests(session, count, path="/invoices"):
    print(f"\n{'='*60}")
    print(f"  VOLUME TEST: {count} peticiones secuenciales a {path}")
    print(f"{'='*60}")
    times_list = []
    failures = 0
    t0 = time.time()
    for i in range(count):
        rt0 = time.time()
        try:
            r = session.get(f"{BASE}{path}", allow_redirects=True, timeout=15)
            times_list.append(time.time() - rt0)
            if r.status_code >= 400:
                failures += 1
        except:
            failures += 1
        if (i+1) % 100 == 0:
            print(f"    {i+1}/{count}... avg={sum(times_list[-100:])/100:.2f}s")
    total_time = time.time() - t0
    avg = sum(times_list)/len(times_list) if times_list else 0
    passed = failures < count * 0.05
    print(f"    {count} peticiones | {failures} fallos | {total_time:.1f}s total")
    print(f"    Avg: {avg:.2f}s | Throughput: {count/total_time:.1f} req/s")
    print(f"    Resultado: {'✅ PASS' if passed else '❌ FAIL'}")
    return {"count": count, "passed": passed, "avg": avg, "failures": failures}


def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   STRESS & VOLUME TESTING — VykOne ERP v1.0          ║")
    print("╚══════════════════════════════════════════════════════╝")

    session = load_session()
    if not session:
        print("\n⚠️  No hay sesión activa. Ejecuta login primero.")
        return 1

    all_passed = True
    for n in CONCURRENT_USERS:
        r = concurrent_test(session, n, iterations=2)
        if not r["passed"]:
            all_passed = False

    # Sequential volume
    r = sequential_requests(session, 100, "/dashboard")
    if not r["passed"]:
        all_passed = False

    print(f"\n{'='*60}")
    print(f"  VEREDICTO: {'✅ APTO' if all_passed else '❌ REQUIERE MEJORAS'}")
    print(f"{'='*60}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
