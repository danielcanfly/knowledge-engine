# M23.7.5 Privacy-Safe Bounded Live Shadow Observation

Parent: #408. Issue: #430.

## Purpose

M23.7.5 authorises one tightly bounded observation of the existing non-production
semantic pilot. It does not authorise production query mirroring or a retrieval-mode
change. The lexical path remains the only response-authoritative path.

Production mutation dispatched: false.

## Entry identities

- Engine entry: `21386886105b5a44130f713b4e92d04f3bfd247d`
- M23.7.1 contract: `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`
- M23.7.2 evaluation: `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`
- M23.7.3 stable replay: `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`
- M23.7.4 composition: `6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7`
- Candidate release: `m23cand-c7fbec7e945e79d05d3263b0`
- Candidate manifest: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`
- Qdrant point release: `m23pilot-a07eb79e381ca7e635cc9139`
- Qdrant point manifest: `a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9`
- Collection: `llm_wiki_m23_pilot_bge_m3_1024`, 107 points
- Vector: named `default`, dimension 1024, Cosine

## Observation path

```text
internal synthetic probe derived from a public pilot section ID
  → query digest calculated in memory
  → lexical primary identity captured first
  → Cloudflare Workers AI @cf/baai/bge-m3
  → read-only Qdrant /points/query
  → ACL and point-identity validation
  → comparison metrics and bounded failure class
  → candidate output discarded
```

The probe text is never a user query. It exists only in process memory and is never
written to the report. The durable report contains probe IDs, query digests, audience,
ranked section IDs, bounded latency measurements, failure classes and identities.

## Bounds

- maximum probes per run: 8;
- audience: public only;
- top-k: 5;
- CI artifact retention: 7 days;
- circuit breaker: 3 failures;
- accepted error rate: 0;
- accepted ACL violation rate: 0;
- accepted output influence rate: 0;
- primary dispatch overhead p95: at most 25 ms;
- total shadow p95: at most 1200 ms.

## Privacy invariants

The report must never contain:

- raw user query text;
- raw answer text;
- credential material;
- service URLs;
- arbitrary exception text;
- private or internal-only evidence.

The live runner maps upstream failures to a closed bounded vocabulary. It never stores
the provider or Qdrant response body on failure.

## Authority invariants

For every probe:

- lexical primary completion is recorded before shadow execution;
- authoritative section IDs remain the lexical IDs;
- candidate output is never served;
- candidate output is discarded after comparison;
- `output_influenced` remains false;
- Qdrant is queried read-only with payloads and without vectors;
- no write, delete, deployment, pointer, R2, Source, ledger or promotion action exists.

## Stop conditions

The run fails closed on collection health or identity drift, wrong point release,
wrong vector name or dimension, non-public audience, response-shape drift, any upstream
failure, point-count change, latency-budget breach, output influence or protected
mutation.

## Live execution procedure

The knowledge-engine repository does not currently hold the four Cloudflare/Qdrant
GitHub Actions secrets. The governed credentials remain in the existing local secret
file and must not be copied into source control.

After the implementation merge, execute from the local repository checkout:

```bash
cd /Users/huaihsuanhuang/Documents/GitHub/knowledge-engine
git switch main
git pull --ff-only
set -a
source /Users/daniel/LLM-Wiki-Local/secrets/m23-5-cloud.env
set +a
mkdir -p /Users/daniel/LLM-Wiki-Local/evidence/m23-7-5
python scripts/m23_7_5_live_shadow.py \
  --mode live \
  --output /Users/daniel/LLM-Wiki-Local/evidence/m23-7-5/live-shadow.json
```

The output is already redacted. Before it may be committed as reconciliation evidence,
verify that it contains no raw query, answer, credential, service URL or arbitrary
exception text. The workflow-dispatch live job is an alternative only after the same
four values are deliberately configured as repository secrets and `execute_live=true`
is explicitly selected.

## Evidence and next gate

The pull-request workflow proves deterministic contract readiness. The real observation
remains a separate explicit operation because the credentials are local, not repository
secrets. Independent reconciliation must seal the accepted implementation head, the
real report SHA, aggregate metrics and no-production-mutation proof before #430 closes.

M23.7.6 remains blocked until M23.7.5 implementation and reconciliation are merged and
issue #430 is closed completed.

Production mutation dispatched: false.
