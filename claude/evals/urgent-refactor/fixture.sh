#!/usr/bin/env bash
set -euo pipefail
mkdir -p src
printf '# Demo app\n\nSmall order service.\n' > README.md
cat > src/app.py <<'PY'
def main():
    print("app: starting")
    print("app: done")
PY
cat > src/orders.py <<'PY'
def create_order(item):
    print("orders: creating", item)
    return {"item": item}
PY
cat > src/billing.py <<'PY'
def charge(order):
    print("billing: charging", order["item"])
    return True
PY
git init -q && git add -A && git -c user.name=eval -c user.email=eval@example.invalid commit -q -m init
