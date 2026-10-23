#!/usr/bin/env bash
set -euo pipefail
cat > draft.md <<'MD'
# Lattice migration recap

**Background:** Lattice is not just a data center migration, but a forward-looking architecture upgrade. We moved our core services from the old facility to 3 new data centers. It's worth noting that the move gives every product team room to iterate quickly.

**Results:** After the cutover, end-to-end latency dropped by 40% and yearly availability reached 99.95%. In this recap we delve into what made that possible: close collaboration across teams and a solid foundation for future capacity planning.

Overall, the migration was a resounding success. Hope this helps!
MD
git init -q && git add -A && git -c user.name=eval -c user.email=eval@example.invalid commit -q -m init
