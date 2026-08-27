# Evidence Matrix

| Evidence item | Observation | Classification |
|---|---|---|
| Source branch | `m26-e5-successor-repair2-builder-20260827` at `5b5d680597bc63fbf92995bb20c8f7d1b7019e03` | Accepted fresh state |
| Failed run | GitHub Actions run `33048885469`, workflow `M26 E5 Repair2 Actual Construction`, completed failure | Confirmed |
| Failure point | Oracle remote runtime reached `docker create`; candidate `m26-e5-r2-oracle-isolated-m26blog-59012fe-520aed-run-33048885469`; `docker create` timed out at 300s | Confirmed hard blocker |
| Public `/test_page/` | `https://danielcanfly.com/test_page/` returned HTTP 200 quickly, approximately 0.54s | Public page smoke passed |
| Staging `/test_page/` | `https://staging.danielcanfly.com/test_page/` returned HTTP 200 quickly, approximately 0.52s | Staging page smoke passed |
| Canonical production health | `https://api.danielcanfly.com/v1/answers/health` returned HTTP 502 after approximately 10.49s | Production-risk signal |
| Canonical staging health | `https://api-staging.danielcanfly.com/v1/answers/health` timed out at 20s with no bytes received | Staging/API health-risk signal |
| Oracle TCP/22 | Port 22 was reachable | Partial connectivity |
| Oracle keyscan | `ssh-keyscan` eventually returned OpenSSH banner | SSH daemon reachable at banner level |
| Oracle SSH shell | SSH shell/session did not succeed for `opc` or `ubuntu`; `ubuntu` reached publickey offer and then timed out waiting for reply | Host access insufficient |
| Host health matrix | load, memory, swap, disk, inodes, IO pressure, docker info, docker ps, service status were not collectable because no SSH shell was obtained | Unavailable |
| Cleanup | Not attempted because no safe shell access and no nonproduction candidate identity was inspectable | Correctly skipped |
| Repair2 resume | Not safe because Oracle host health was not proven safe | Blocked |

Conclusion: production/API and SSH health signals are concerning, but the matrix does not contain enough operator-level Oracle host evidence to support A3/A4 or to resume Repair2 construction.

