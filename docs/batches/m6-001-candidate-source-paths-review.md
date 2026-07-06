# M6-001 Candidate Source Paths Review

Status: `path review only`

Parent tracker: `#42`

Child slice: `#53`

Source repository: `danielcanfly/knowledge-source`

Source HEAD reviewed: `6a35f9f35e4c6c599a266710344f760c399d914d`

Inventory timestamp: `20260706T152049Z`

Inventory checksum: `375dfe63eaeae00e1aa5a350d98e60f43412f6bc19f15689279fd44ceca9eb57`

This document classifies the paths found by the local inventory. It is planning evidence only.

## 1. Inventory summary

- Total files: `21`
- Text-like files: `14`
- Keyword-hit files: `9`

Keyword-hit paths:

- `README.md`
- `bundle/concepts/candidate-delivery-controls.md`
- `bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md`
- `bundle/concepts/source-governance.md`
- `bundle/index.md`
- `provenance/six-dimensional-map-of-llm-agent-architectures.json`
- `provenance/source-governance.json`
- `registry/reviews.json`
- `registry/sources.json`

## 2. Review facts

Observed from Source files at the reviewed SHA:

- `bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md` is a published public concept.
- `bundle/concepts/source-governance.md` is a published public concept.
- `bundle/concepts/candidate-delivery-controls.md` is a reviewed non-public concept.
- `registry/reviews.json` confirms public review for the six-dimensional map and source governance concepts.
- `registry/reviews.json` confirms non-public review for candidate delivery controls.
- `registry/sources.json` records the public URL for the six-dimensional map concept.

## 3. Path classification

| Source path | Role | Decision | Proposed use |
| --- | --- | --- | --- |
| `bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md` | public concept | include | public candidate content |
| `bundle/concepts/source-governance.md` | public concept | include | public candidate content |
| `bundle/concepts/candidate-delivery-controls.md` | non-public concept | do not include as public content | access-control fixture only |
| `bundle/index.md` | bundle index | support only | navigation / supporting check |
| `README.md` | repository guidance | support only | operator context |
| `registry/sources.json` | metadata | support only | source metadata evidence |
| `registry/reviews.json` | metadata | support only | review metadata evidence |
| `provenance/six-dimensional-map-of-llm-agent-architectures.json` | metadata | support only | provenance evidence |
| `provenance/source-governance.json` | metadata | support only | provenance evidence |

## 4. Recommended M6-001 scope

Recommended primary content paths:

- `bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md`
- `bundle/concepts/source-governance.md`

Recommended supporting paths:

- `bundle/index.md`
- `registry/sources.json`
- `registry/reviews.json`
- `provenance/six-dimensional-map-of-llm-agent-architectures.json`
- `provenance/source-governance.json`

Recommended non-public fixture path:

- `bundle/concepts/candidate-delivery-controls.md`

Not recommended as primary content:

- `README.md`

## 5. Proposed public acceptance coverage

The two primary content paths support these acceptance families:

- Knowledge Source governance and the human-authored Source boundary.
- Six-dimensional review of LLM agent architecture patterns.

The exact query strings should be finalized in the next M6 planning step.

## 6. Candidate table for proposal update

| Source path | Candidate family | Rationale | Citation target | Proposed decision |
| --- | --- | --- | --- | --- |
| `bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md` | production-RAG / agent architecture notes | Public reviewed concept. | `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/` | include |
| `bundle/concepts/source-governance.md` | Knowledge OS governance notes | Public reviewed concept. | Source-backed target pending runtime mapping. | include |
| `bundle/concepts/candidate-delivery-controls.md` | governance notes | Reviewed non-public concept. | n/a for public acceptance | fixture only |
| `bundle/index.md` | index support | Links reviewed bundle concepts. | Source-backed target pending runtime mapping. | support only |
| `registry/sources.json` | metadata | Confirms source metadata. | metadata only | support only |
| `registry/reviews.json` | metadata | Confirms review decisions. | metadata only | support only |
| `provenance/six-dimensional-map-of-llm-agent-architectures.json` | metadata | Supports provenance chain. | metadata only | support only |
| `provenance/source-governance.json` | metadata | Supports provenance chain. | metadata only | support only |
| `README.md` | repository guidance | Useful context but not primary concept content. | n/a | support only |

## 7. Next step

Update the M6-001 Source PR proposal with this reviewed candidate table. Do not move to candidate build planning until Source validation evidence is recorded.
