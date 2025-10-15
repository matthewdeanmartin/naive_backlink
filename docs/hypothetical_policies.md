Big Organization Policy
---
Ban anonymous packages anywhere in the chain
- Doesn't apply to "lost track of who this was". Tooling can help here by finding a package with *no claims* of identity. 

Stop installation & investigate
- New dependency in graph (new dependency could be a old package with many downloads)
- Dependency in graph (root or indirect) itself is brand new
- Strong and weak claims stop matching
  - No backlinks
  - Backlinks have changed

Investigation
- Gathering reputation info
- Gathering diff info (what changed since a known trusted package)
- Reading and reviewing code (ruinously expensive, would need to crowdsource this)