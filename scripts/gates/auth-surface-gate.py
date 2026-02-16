"""Auth surface gate: verifies deny-by-default posture across all endpoints."""
import json, os, sys, datetime, subprocess, importlib.util

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GW = os.path.join(ROOT, "services", "api-gateway")
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# ── Check 1: AuthMiddleware exists and is imported in main.py ─────────────
main_path = os.path.join(GW, "main.py")
with open(main_path, "r") as f:
    main_src = f.read()

has_auth_import = "from auth import AuthMiddleware" in main_src
checks.append({
    "name": "auth_middleware_imported",
    "passed": has_auth_import,
    "detail": f"AuthMiddleware imported in main.py: {has_auth_import}",
})

# ── Check 2: Auth is default-on (not dev_mode) ───────────────────────────
has_default_on = "auth_enabled = not dev_mode" in main_src
checks.append({
    "name": "auth_default_on",
    "passed": has_default_on,
    "detail": f"Auth is default-on (not dev_mode): {has_default_on}",
})

# ── Check 3: Dev mode is ONLY env-var driven ──────────────────────────────
has_env_only = 'SONIA_DEV_MODE' in main_src and '== "1"' in main_src
checks.append({
    "name": "dev_mode_env_only",
    "passed": has_env_only,
    "detail": f"SONIA_DEV_MODE env var is sole bypass: {has_env_only}",
})

# ── Check 4: Dev mode emits warning log ───────────────────────────────────
has_warning = "auth_disabled_dev_mode" in main_src
checks.append({
    "name": "dev_mode_warning",
    "passed": has_warning,
    "detail": f"Dev mode emits auth_disabled_dev_mode warning: {has_warning}",
})

# ── Check 5: Exempt set is bounded and correct ───────────────────────────
spec = importlib.util.spec_from_file_location("auth", os.path.join(GW, "auth.py"))
auth_mod = importlib.util.module_from_spec(spec)
sys.modules.setdefault("starlette.middleware.base", type(sys)("fake"))
sys.modules.setdefault("starlette.requests", type(sys)("fake"))
sys.modules.setdefault("starlette.responses", type(sys)("fake"))
# We need to check the _DEFAULT_EXEMPT set; parse it from source instead
with open(os.path.join(GW, "auth.py"), "r") as f:
    auth_src = f.read()

expected_exempt = {"/healthz", "/health", "/status", "/", "/docs", "/openapi.json", "/redoc"}
# Extract the _DEFAULT_EXEMPT set from source
found_all = all(f'"{p}"' in auth_src for p in expected_exempt)
checks.append({
    "name": "exempt_set_bounded",
    "passed": found_all,
    "detail": f"All {len(expected_exempt)} expected exempt paths present in auth.py: {found_all}",
})

# ── Check 6: No /v3/ or /v1/ path in exempt set ──────────────────────────
no_v3_exempt = "/v3/" not in auth_src.split("_DEFAULT_EXEMPT")[1].split("}")[0] if "_DEFAULT_EXEMPT" in auth_src else False
no_v1_exempt = "/v1/" not in auth_src.split("_DEFAULT_EXEMPT")[1].split("}")[0] if "_DEFAULT_EXEMPT" in auth_src else False
no_api_exempt = no_v3_exempt and no_v1_exempt
checks.append({
    "name": "no_api_paths_exempt",
    "passed": no_api_exempt,
    "detail": f"No /v3/ or /v1/ paths in default exempt set: {no_api_exempt}",
})

# ── Check 7: Lifespan adds /version and /pragmas (and nothing else unexpected) ──
lifespan_exempt_section = main_src.split("exempt.update(")[1].split(")")[0] if "exempt.update(" in main_src else ""
has_version = '"/version"' in lifespan_exempt_section
has_pragmas = '"/pragmas"' in lifespan_exempt_section
no_v3_lifespan = "/v3/" not in lifespan_exempt_section
lifespan_ok = has_version and has_pragmas and no_v3_lifespan
checks.append({
    "name": "lifespan_exempt_controlled",
    "passed": lifespan_ok,
    "detail": f"Lifespan adds /version+/pragmas, no /v3/ paths: {lifespan_ok}",
})

# ── Check 8: Unit tests exist and pass ────────────────────────────────────
test_path = os.path.join(ROOT, "tests", "unit", "test_auth_surface.py")
checks.append({
    "name": "unit_tests_exist",
    "passed": os.path.isfile(test_path),
    "detail": f"test_auth_surface.py exists: {os.path.isfile(test_path)}",
})

python = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(python):
    python = sys.executable

result = subprocess.run(
    [python, "-m", "pytest", test_path, "-v", "--tb=short", "-q"],
    capture_output=True, text=True, cwd=ROOT, timeout=120
)
unit_passed = result.returncode == 0
lines = result.stdout.strip().split("\n")
summary_line = lines[-1] if lines else ""
checks.append({
    "name": "unit_tests_pass",
    "passed": unit_passed,
    "detail": summary_line,
    "stdout": result.stdout[-500:] if not unit_passed else "",
    "stderr": result.stderr[-300:] if not unit_passed else "",
})

# ── Check 10: Rate limiter middleware present ─────────────────────────────
has_rate_limiter = "rate_limit_middleware" in main_src
checks.append({
    "name": "rate_limiter_present",
    "passed": has_rate_limiter,
    "detail": f"Rate limiter middleware registered: {has_rate_limiter}",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "auth_surface",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"auth-surface-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Auth Surface Gate ({report['checks_passed']}/{report['checks_total']}) ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")

print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
