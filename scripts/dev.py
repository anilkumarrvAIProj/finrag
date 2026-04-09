#!/usr/bin/env python3
"""
FinRAG Development Helper Scripts

Usage:
  python scripts/dev.py bootstrap       — Start services, run migrations, create dev token
  python scripts/dev.py seed            — Seed test documents
  python scripts/dev.py token [role]    — Get a dev JWT token
  python scripts/dev.py status          — Show service health
  python scripts/dev.py weaviate-init   — Create Weaviate schema
"""
import sys
import subprocess
import requests
import json
from datetime import datetime

API = "http://localhost:8000"


def bootstrap():
    print("🚀 FinRAG Bootstrap")
    print("Starting services...")
    subprocess.run(["docker", "compose", "up", "-d"], check=True)

    print("\nWaiting for API...")
    import time
    for i in range(30):
        try:
            r = requests.get(f"{API}/health", timeout=3)
            if r.ok:
                print(f"  ✓ API ready ({r.json()['status']})")
                break
        except Exception:
            pass
        time.sleep(2)
        if i % 5 == 0:
            print(f"  … waiting ({i*2}s)")

    print("\nRunning migrations...")
    subprocess.run([
        "docker", "compose", "exec", "backend",
        "alembic", "upgrade", "head"
    ], check=True)
    print("  ✓ Migrations applied")

    print("\nInitializing Weaviate schema...")
    token = get_token("admin")
    r = requests.get(f"{API}/api/v1/admin/health", headers={"Authorization": f"Bearer {token}"})
    print(f"  Weaviate: {r.json().get('vector_store', 'unknown')}")

    print("\n✅ Bootstrap complete!")
    print(f"  Admin Portal: http://localhost:3000")
    print(f"  Chat UI:      http://localhost:3001")
    print(f"  API Docs:     http://localhost:8000/docs")
    print(f"  Dev Token:    {token[:40]}…")


def get_token(role: str = "admin") -> str:
    r = requests.post(f"{API}/api/v1/auth/dev-token?role={role}")
    r.raise_for_status()
    return r.json()["access_token"]


def token(role: str = "admin"):
    t = get_token(role)
    print(f"\n🔑 Dev token (role={role}):")
    print(t)
    print(f"\nExpires: 8 hours from now")
    print(f"\nUsage:")
    print(f'  curl -H "Authorization: Bearer {t[:30]}..." http://localhost:8000/api/v1/documents')


def seed():
    """Seed test documents by uploading sample PDFs."""
    import io
    t = get_token("admin")
    headers = {"Authorization": f"Bearer {t}"}

    print("📄 Seeding test documents...")

    # Create a minimal PDF (just enough to test the pipeline)
    test_docs = [
        ("ABC_Growth_Fund_FactSheet_Q3_2025.pdf", "fact_sheet",
         b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
         b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
         b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
         b"/Contents 4 0 R>>endobj\n"
         b"4 0 obj<</Length 150>>stream\n"
         b"BT /F1 12 Tf 72 720 Td (ABC Growth Fund - Fact Sheet Q3 2025) Tj\n"
         b"0 -20 Td (Total AUM: $4.2 Billion) Tj\n"
         b"0 -20 Td (Net Return Q3: 7.2%) Tj ET\nendstream\nendobj\n"
         b"xref\n0 5\n0000000000 65535 f\n"
         b"trailer<</Size 5/Root 1 0 R>>\nstartxref\n9\n%%EOF"),
    ]

    for filename, doc_type, content in test_docs:
        files = {"file": (filename, io.BytesIO(content), "application/pdf")}
        data = {"doc_type": doc_type}
        r = requests.post(f"{API}/api/v1/documents/upload", files=files, data=data, headers=headers)
        if r.ok:
            print(f"  ✓ {filename} → {r.json()['id'][:8]}… (status: {r.json()['status']})")
        else:
            print(f"  ✗ {filename}: {r.status_code} {r.text[:100]}")


def status():
    print("📊 FinRAG Service Status\n")
    try:
        r = requests.get(f"{API}/health", timeout=5)
        data = r.json()
        print(f"  API:      {data['status']} (v{data['version']})")
    except Exception:
        print("  API:      ✗ unreachable")
        return

    try:
        t = get_token("admin")
        r = requests.get(f"{API}/api/v1/admin/health", headers={"Authorization": f"Bearer {t}"}, timeout=10)
        h = r.json()
        print(f"  Database: {h.get('database', '?')}")
        print(f"  Cache:    {h.get('cache', '?')}")
        print(f"  Vectors:  {h.get('vector_store', '?')}")
        print(f"  Status:   {h.get('status', '?')}")
        if h.get("queue_depths"):
            print(f"\n  Queue depths:")
            for q, d in h["queue_depths"].items():
                print(f"    {q}: {d}")
    except Exception as e:
        print(f"  Admin health check failed: {e}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    role_arg = sys.argv[2] if len(sys.argv) > 2 else "admin"

    commands = {
        "bootstrap": bootstrap,
        "seed": seed,
        "token": lambda: token(role_arg),
        "status": status,
    }

    fn = commands.get(cmd)
    if fn:
        fn()
    else:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands.keys())}")
        sys.exit(1)
