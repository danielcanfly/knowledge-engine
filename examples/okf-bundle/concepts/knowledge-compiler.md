---
type: Concept
title: Knowledge Compiler
description: A deterministic pipeline that compiles reviewed knowledge into immutable runtime releases.
timestamp: 2026-07-02T12:00:00Z
x-kos-id: ko_01JXYZ123456789ABCDEFGHJKM
x-kos-status: published
x-kos-audience: internal
x-kos-confidence: 0.96
x-kos-provenance: provenance/knowledge-compiler.json
x-kos-review:
  status: approved
  reviewer: daniel
  reviewed_at: 2026-07-02T11:30:00Z
---
# Knowledge Compiler

A Knowledge Compiler validates reviewed OKF knowledge, derives runtime indexes, and publishes an immutable release before changing a channel pointer.

# Operational rule

The channel pointer changes only after every release object has passed integrity verification.
