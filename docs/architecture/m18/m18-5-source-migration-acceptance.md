# M18.5 exact Source migration acceptance

This acceptance gate checks out merged Source SHA
`1a4b4030b6b25a58ff3edba204e303ae1f95b931` and builds it twice with the
current Engine using isolated filesystem object stores.

The gate requires byte-identical releases, five graph v2 nodes, three authored
relations, five compiled typed edges after directed inverse generation, nineteen
controlled tag assignments, ten aliases, public ACL on all migrated edges, and
zero renderer-specific fields.

The five concepts remain unchanged in count. Governance and candidate controls
remain unconnected because their reviewed evidence does not support canonical
relations to the agent concepts. The gate performs no candidate or production
publication and does not access R2.
