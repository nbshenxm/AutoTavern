# Sourced by BG's office scripts: the CPUs BG may use on the shared office machine (BG_CPUS
# overrides). Until plan2's end (2026-11-12 20:00) BG has 0-11; from then 0-7, and the
# constructed track gets 8-11 beside its 12-23 (the user's choice, Nov 10).
if [ -z "${BG_CPUS:-}" ]; then
    if [ "$(date +%s)" -ge "$(date -d '2026-11-12 20:00' +%s)" ]; then BG_CPUS=0-7; else BG_CPUS=0-11; fi
fi
# The number of CPUs in BG_CPUS (for thread counts): "0-7" -> 8, "0-3,6" -> 5
BG_NCPU=0
for part in ${BG_CPUS//,/ }; do
    a=${part%-*}; b=${part#*-}; BG_NCPU=$((BG_NCPU + b - a + 1))
done
export BG_CPUS BG_NCPU
