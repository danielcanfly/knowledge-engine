# M23.7 R3.8.48 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29564569280`.

The authorization is based on the worker-present recovery seal merged in PR #738
and the independent reconciliation merged in PR #740. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29565032873`.

## Bound Evidence

- Observation run: `29564569280`
- Recovery run: `29565032873`
- Recovery receipt SHA-256:
  `8576942d225bd82c3efd150c6aac0f93355386ab3c151ff98beff24e9b7cb779`
- Evidence seal SHA-256:
  `3a6e8e2d1bf8127aad0ef4b090528cb0dbe7997c488c6d681b68f503edcceb4f`
- Independent reconciliation SHA-256:
  `01b2e036f51a9eeef8b01713f2470d039da8d32cb0f08610986b57e1991fb6e6`
- Authorization SHA-256:
  `7cd2c6377f85544804fd06e4d9dbbdb9158f69933bd77b9edcf4ee9e7454ae4f`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
