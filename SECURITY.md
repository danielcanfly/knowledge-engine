# Security

Production credentials and deployment keys must stay outside source control.

Production authentication uses Supabase JWT verification through JWKS. The Runtime does not trust caller-supplied audience lists. Confidential and restricted access require a signed `knowledge_audiences` claim.

Release integrity is verified before activation. A failed refresh leaves the last-known-good release active.
