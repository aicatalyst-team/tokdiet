#!/usr/bin/env python3
"""PoC validation tests for TokDiet deployed on OpenShift.

Tests the dashboard and proxy endpoints via in-cluster service URLs.
Uses only Python stdlib (urllib.request) for portability.
"""
import json
import sys
import time
import urllib.request
import urllib.error

DASHBOARD_URL = "http://tokdiet.poc-tokdiet.svc:7878"
PROXY_URL = "http://tokdiet.poc-tokdiet.svc:7787"
MAX_RETRIES = 5
RETRY_DELAY = 10

results = []


def test_with_retry(name, url, check_fn, description=""):
    """Run a test with retry logic."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        start = time.time()
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json, text/html, */*")
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = resp.status
                body = resp.read().decode("utf-8", errors="replace")
                duration = time.time() - start

                ok, detail = check_fn(status, body)
                if ok:
                    results.append({
                        "scenario_name": name,
                        "status": "pass",
                        "output": detail[:500],
                        "error_message": None,
                        "duration_seconds": round(duration, 2),
                    })
                    print(f"  PASS: {name} ({duration:.2f}s) - {detail[:100]}")
                    return True
                else:
                    last_error = f"Check failed: {detail}"
        except urllib.error.HTTPError as e:
            duration = time.time() - start
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            # For some tests, certain HTTP errors are acceptable
            ok, detail = check_fn(e.code, body)
            if ok:
                results.append({
                    "scenario_name": name,
                    "status": "pass",
                    "output": detail[:500],
                    "error_message": None,
                    "duration_seconds": round(duration, 2),
                })
                print(f"  PASS: {name} ({duration:.2f}s) - {detail[:100]}")
                return True
            last_error = f"HTTP {e.code}: {body[:200]}"
        except Exception as e:
            duration = time.time() - start
            last_error = f"{type(e).__name__}: {str(e)[:200]}"

        if attempt < MAX_RETRIES:
            print(f"  RETRY {attempt}/{MAX_RETRIES}: {name} - {last_error}")
            time.sleep(RETRY_DELAY)

    # All retries exhausted
    results.append({
        "scenario_name": name,
        "status": "fail",
        "output": "",
        "error_message": last_error,
        "duration_seconds": 0,
    })
    print(f"  FAIL: {name} - {last_error}")
    return False


def check_dashboard_summary(status, body):
    """Check /api/summary returns 200 with JSON."""
    if status != 200:
        return False, f"Expected 200, got {status}"
    try:
        data = json.loads(body)
        return True, json.dumps(data)[:300]
    except json.JSONDecodeError:
        return False, f"Response is not valid JSON: {body[:100]}"


def check_dashboard_html(status, body):
    """Check / returns 200 with HTML content."""
    if status != 200:
        return False, f"Expected 200, got {status}"
    if "<html" in body.lower() or "<!doctype" in body.lower():
        return True, "Dashboard HTML page loaded successfully"
    return False, f"Response does not contain HTML: {body[:100]}"


def check_proxy_listening(status, body):
    """Check proxy port is accepting connections. Any response means it's alive."""
    # The proxy expects POST with JSON body. A bare GET will return 400 or 502,
    # but that's fine - it proves the port is listening.
    return True, f"Proxy responded with HTTP {status} (port is listening)"


def main():
    print("=" * 60)
    print("TokDiet PoC Validation Tests")
    print("=" * 60)
    print(f"Dashboard URL: {DASHBOARD_URL}")
    print(f"Proxy URL:     {PROXY_URL}")
    print()

    # Test 1: Dashboard /api/summary (JSON health endpoint)
    print("[Test 1] Dashboard API Summary:")
    test_with_retry("health-check", f"{DASHBOARD_URL}/api/summary", check_dashboard_summary)
    print()

    # Test 2: Dashboard root / (HTML page)
    print("[Test 2] Dashboard UI:")
    test_with_retry("dashboard-ui", f"{DASHBOARD_URL}/", check_dashboard_html)
    print()

    # Test 3: Proxy port listening
    print("[Test 3] Proxy Status:")
    test_with_retry("proxy-status", f"{PROXY_URL}/", check_proxy_listening)
    print()

    # Summary
    print("=" * 60)
    passed = sum(1 for r in results if r["status"] == "pass")
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)

    # Output JSON results to stdout
    print("\n--- JSON RESULTS ---")
    print(json.dumps(results, indent=2))

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
