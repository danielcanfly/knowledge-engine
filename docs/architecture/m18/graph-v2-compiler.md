# Graph schema v2 compiler

M18.4 adds a deterministic, renderer-neutral graph v2 artifact while retaining
`artifacts/graph.json` schema v1 for existing Runtime consumers.

Graph v2 nodes carry stable identity, description, ACL, status, confidence, governed
tags and aliases, path, and provenance identity. Typed edges derive deterministic IDs
from immutable endpoint IDs, relation type, direction, sorted qualifiers, and schema
version. Directed authoring relations emit generated inverse semantics.

Generic Markdown links remain in the v1 compatibility graph and are not promoted into
typed facts. Coordinates, colours, sizes, Sigma fields, and other renderer state fail
closed. Current Runtime query behavior is unchanged and relation-aware expansion remains
disabled until M18.6.

No build performed by this milestone is published to candidate or production.
