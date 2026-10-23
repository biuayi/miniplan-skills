#!/usr/bin/env bash
set -euo pipefail
mkdir -p src
printf '# Demo\n\nAuth, orders and reporting helpers.\n' > README.md
cat > src/auth.py <<'PY'
def login(user, password):
    return user == "admin" and password == "secret"

def logout(session):
    session.clear()
PY
cat > src/orders.py <<'PY'
def create_order(item):
    return {"item": item}

def cancel_order(order):
    order["cancelled"] = True
PY
cat > src/report.py <<'PY'
def summary(orders):
    return len(orders)

def render(orders):
    return "\n".join(o["item"] for o in orders)
PY
git init -q && git add -A && git -c user.name=eval -c user.email=eval@example.invalid commit -q -m init
