# M23.7-R3.8.8 Artifact Recovery Independent Reconciliation

## Reconciled implementation

- implementation issue: #538
- implementation PR: #539
- accepted head: `15acedbeaf0fd0ad2857ea8365ac23b0f311e22e`
- squash merge: `e29591e3603b528e13662f7956b852f1da3594a8`
- recovery contract: `508111abd2d6291f1b13b44956811d9028b4832d26caeb8ec6905e693928dc33`
- reconciliation digest: `0b8108e29057f8817994ffba63e5724be18db83bd38e386304fdc403fb872b4f`

The eleven changed files match PR #539. Exact-head runs succeeded for R3.8.8
artifact recovery, the forward-compatible R3.8.7 remote-operator regression gate,
global CI, M17 and M18.

## Incident conclusion

GitHub Actions run `29506217284` remains classified as:

```text
rejected_incomplete_remote_observation_evidence_loss
```

The run produced zero retained artifacts because its evidence directory was hidden
from `actions/upload-artifact@v4`. The operator exit class was not preserved in run
metadata. Therefore the run is neither a latency acceptance result nor a quality
acceptance result.

The deterministic Worker name is:

```text
knowledge-engine-r3-8-29506217284
```

Its state remains `unknown`. This reconciliation makes no claim that the Worker is
absent or present. Run `29506217284` must never be rerun.

## Reconciled repair

- observation evidence uses non-hidden `r3-8-remote-evidence/`;
- deletion evidence uses non-hidden `r3-8-deletion-evidence/`;
- a bounded entrypoint writes privacy-safe evidence before importing the operator;
- the recovery workflow is manual, exact-head and read-only;
- the recovery probe is fixed to run `29506217284` and its deterministic Worker;
- only Cloudflare versions and deployments GET requests are authorized.

The recovery probe has not yet executed. During implementation and reconciliation,
no Worker deploy, delete, secret mutation or route invocation occurred. No Qdrant or
R2 read or mutation occurred. No protected state was changed.

## Frozen authority

Production retrieval remains lexical. The Worker-internal maximum remains `1200 ms`.
The following blockers remain active:

- `blocked_pending_retrieval_quality`
- `blocked_pending_latency`

No fresh observation or orphan deletion is authorized. Issues #520 and #474 remain
open, and M23.7 closure is not authorized.

## Next legal gate

Dispatch `M23.7 R3.8.8 Recovery Probe` once from the exact accepted main head with:

```text
affected_run_id = 29506217284
confirmation = PROBE_R3_8_RUN_29506217284
```

The resulting artifact must be independently validated and reconciled before any
fresh observation, orphan cleanup or blocker decision.
