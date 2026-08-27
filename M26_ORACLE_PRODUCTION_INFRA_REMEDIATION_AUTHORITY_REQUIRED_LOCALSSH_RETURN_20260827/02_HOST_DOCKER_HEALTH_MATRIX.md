# Host And Docker Health Matrix

Collection window:

- begin: `2026-08-27T09:52:30Z`
- end: `2026-08-27T09:55:28Z`
- transport: local SSH alias `oracle-vm`
- mutation posture: read-only
- docker create latency: `NOT_COLLECTED_NONPROD_CREATE_PROBE_NOT_AUTHORIZED`
- diagnostic docker create mutations: `0`

Host identity:

| Check | Evidence |
|---|---|
| user | `ubuntu` |
| hostname | `vm-dev-01` |
| kernel | `Linux vm-dev-01 6.17.0-1019-oracle #19~24.04.3-Ubuntu SMP Thu Jul 16 17:39:35 UTC 2026 x86_64` |
| vCPU | `2` |
| uptime | `22 days, 5:03` |

Resource health:

| Check | Evidence | Classification |
|---|---|---|
| load average | `21.75, 23.15, 21.91` on 2 vCPU | Unsafe/high saturation |
| memory | 954 MB total, 744 MB used, 50 MB free, 209 MB available | Constrained |
| swap | 2047 MB used of 2047 MB | Unsafe/full swap |
| root disk | `/dev/sda1` 45G size, 36G used, 8.8G free, 81% used | Elevated but not full |
| root inodes | 23% used | Not inode-bound |
| CPU pressure | `some avg10=91.73 avg60=87.95 avg300=88.81` | Unsafe |
| memory pressure | `some avg10=64.75 avg60=40.93 avg300=43.08`, `full avg10=10.35` | Unsafe |
| IO pressure | `some avg10=85.36 avg60=79.97 avg300=78.75`, `full avg10=2.92` | Unsafe |
| vmstat | runnable/blocked queues high; swap full; CPU steal reported around 94-95 in sample rows | Unsafe/noisy host scheduling |

Service state:

| Check | Evidence | Classification |
|---|---|---|
| ssh | `active` | Active |
| docker | `active` | Nominally active |
| containerd | `active` | Nominally active |

Docker CLI/daemon responsiveness:

| Check | Evidence | Classification |
|---|---|---|
| `docker version` | client printed, server side did not complete within 20s; `RC=124` | Docker daemon/API unresponsive |
| `docker info` | client printed, server section did not complete within 20s; `RC=124` | Docker daemon/API unresponsive |
| `docker ps -a` | `RC=124` | Docker daemon/API unresponsive |
| production inspect | daemon socket connect/inspect timed out; `RC=124` | Production identity not safely readable |
| production port | `RC=124` | Not readable |
| `m26-e5-*` candidates | `RC=124` | Not readable |
| recent docker events | `RC=124` | Not readable |

Conclusion:

Oracle shell access is available, but the host is under severe resource pressure and Docker daemon/API is not responsive enough for safe Repair2 candidate construction.

