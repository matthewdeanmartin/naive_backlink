# PEP: Naive Backlink Checker

- **PEP**: TBD
- **Title**: Naive Backlink Checker for Non‑Cryptographic Identity Linking
- **Author**: Matthew D. Martin <matthewdeanmartin@gmail.com>, “ChatGPT (spec scribe)”
- **Status**: Draft
- **Type**: Standards Track (Library/API/CLI)
- **Created**: 2025‑10‑13
- **Python-Version**: 3.10+
- **Post-History**: TBD

## Abstract

This PEP specifies a minimal, auditable method for detecting, classifying, and scoring *backlinks* among public web
resources to infer soft identity control without cryptography. A *backlink* exists when **Page A** links to **Page B**,
and **Page B** links back (directly or indirectly) to **Page A** or a page under the same verified control. We define
classes of backlinks (strong, weak, indirect), trusted and untrusted surfaces, evidence records, a scoring function, and
a reference CLI/API.

## Motivation

Package ecosystems (e.g., PyPI) frequently depend on social proofs rather than cryptographic attestations. Maintainers
embed outbound links—social profiles, blogs, code forges—that may in turn link back. Detecting such backlink structures
can produce a practical, explainable identity signal when cryptographic signatures or platform‑provided verification are
unavailable or underutilized.

Use cases:

1. **Coordinated self‑assertion**: Authors deliberately publish reciprocal links (e.g., PyPI project → Mastodon profile
   with `rel="me"` → PyPI project). A build or CI tool verifies the backlink.
2. **Uncoordinated discovery**: Authors accidentally create corroborating trails (e.g., README lists socials; those
   socials link to the PyPI project page or author profile). A tool harvests links, classifies evidence, and presents an
   explainable score.

## Terminology

- **Origin Page (OP)**: The page for which identity corroboration is sought (e.g., a PyPI project page or a maintainer
  profile page).
- **Candidate Page (CP)**: A page linked from OP or discovered via link expansion.
- **Backlink**: A link from CP returning to OP (or an equivalent page that asserts control of OP), either directly or
  via a bounded redirect/hop chain.
- **Strong Backlink**: A backlink using robust semantics, e.g. `<a rel="me" href=...>` on a user‑controlled
  page/profile, or a platform‑level “verified link” mechanism.
- **Weak Backlink**: A simple hyperlink on a user‑controlled page lacking `rel="me"` or platform verification.
- **Indirect Backlink**: A corroboration path requiring one or more intermediate profile pages (e.g., OP → GitHub repo →
  GitHub user profile → OP).
- **Trusted Surface**: A site or page type that is plausibly controlled by the claimed user (e.g., Mastodon profile
  pages, GitHub user profile, personal domain).
- **Untrusted Surface**: Aggregators, mirrors, search results, paste sites, or content where authorship cannot be
  reliably bound to the claimant.

## Non‑Goals

- No cryptographic verification (PGP, DKIM, sigstore) and no reliance on external identity providers beyond public HTTP(
  S).
- No crawler designed for adversarial sites (anti‑bot evasion, CAPTCHA solving, JavaScript execution). The reference
  implementation is fetch‑and‑parse with conservative time and hop limits.

## Specification

### 1. Evidence Model

The checker emits structured *Evidence Records* accumulated during a bounded crawl.

```json
{
  "id": "e-backlink-001",
  "kind": "backlink|mention|redirect|profile|rel-me|platform-verified",
  "source": {
    "url": "https://pypi.org/project/foo/",
    "context": "origin-page"
  },
  "target": {
    "url": "https://mastodon.social/@alice",
    "context": "candidate-page"
  },
  "link": {
    "html": "<a rel=\"me\" href=\"https://pypi.org/project/foo/\">",
    "rel": [
      "me"
    ],
    "nofollow": false
  },
  "classification": "strong|weak|indirect",
  "hops": 1,
  "trusted_surface": true,
  "observed_at": "2025-10-13T16:20:00Z",
  "notes": "Direct rel=me backlink from Mastodon profile to OP"
}
```

- IDs MUST be stable strings (no bare ordinals). Suggested format: `e-<category>-<short-hash>`.
- `kind` distinguishes raw observations (e.g., redirect) from derived facts (e.g., classification).
- `hops` is the length of the shortest observed path from CP back to OP (1 for direct backlinks).

### 2. Backlink Classes

**Strong**

- Link elements with `rel~="me"` from CP to OP or a canonical equivalent.
- Platform‑verified links where the platform explicitly implements identity linking (e.g., Mastodon “verified link” via
  `rel="me"`; GitHub profile “Website” field when it visibly renders as a link on the user profile).
- Same‑domain control assertion (e.g., TXT file or HTML link on `https://example.com/` pointing to OP) when the domain
  is under the subject’s control (heuristically inferred; see §5).

**Weak**

- Plain hyperlinks from CP to OP on user‑controlled pages (no `rel="me"`).
- Links embedded in READMEs or blog posts under the user’s domain/account, including `.md`, `.rst`, `.ipynb`, `.html`
  rendered content.

**Indirect**

- Multi‑hop profile trails: OP → GitHub repo → GitHub profile → OP.
- Organization pages linking to an individual who then links back to OP.

**Excluded**

- Search engine result pages, URL shorteners without resolvable final targets, generic mirrors/archives that mass‑link
  to many projects (e.g., libraries.io project mirrors) unless the page is demonstrably user‑controlled.
- Pastebins and ephemeral dumps.

### 3. Trusted/Untrusted Surfaces

The checker maintains two evolving lists and one heuristic policy.

- **Trusted (examples, non‑exhaustive)**
    - Federated microblog: `*.social`, Mastodon instances where user profiles expose content and allow `rel="me"`.
    - Centralized social: `twitter.com`/`x.com` user pages (posts or bio), `bsky.app` profiles.
    - Code forges: `github.com/<user>`, `gitlab.com/<user>`, `bitbucket.org/<user>`, including profile pages and
      repository READMEs owned by the user/org.
    - Personal domains the subject plausibly controls (see §5).
    - Employment networks: `linkedin.com/in/<slug>` (bio, featured links).

- **Untrusted (blacklist examples)**
    - Search engines: `google.*`, `bing.com`, `duckduckgo.com`, etc.
    - Aggregators/mirrors: `libraries.io`, `grep.app`, `sourcegraph.com` (except authenticated, user profile pages under
      the claimant’s control).
    - Paste sites: `pastebin.com`, `gist.github.com` *unless owned by the claimant* (gists owned by claimant MAY be
      treated as weak if profile page corroborates ownership).
    - Link shorteners unless resolved to a trusted final target, with hop limits: `t.co`, `bit.ly`, `tinyurl.com`, etc.

- **Policy**: Sites not in either list are evaluated via heuristics in §5.

### 4. Content Types

- Treat `.md`, `.rst`, `.html`, and code files (`.py`, `.txt`) as potential containers of hyperlinks when served from a
  user‑controlled context (repo README, personal site). Classification remains *weak* unless `rel="me"` is detected in
  rendered HTML or platform verification exists.

### 5. Heuristics for Control and Canonicalization

- **User Control**
    - Profiles under well‑known paths (e.g., `github.com/<user>`) are user‑controlled.
    - Personal domains: presume user control if OP or another trusted surface explicitly claims the domain (OP →
      `https://example.com/`), and the site links back to OP within MAX_HOPS (default 2). Absent corroboration, classify
      as *weak*.

- **Canonicalization**
    - Normalize URLs: lower‑case scheme+host, remove default ports, strip fragments, preserve path/query.
    - Follow up to MAX_REDIRECTS (default 5). Each redirect becomes an `EvidenceRecord(kind="redirect")`.
    - Permit equivalence classes for OP (e.g., `https://pypi.org/project/foo/` ≡ `https://pypi.org/project/foo`) and for
      canonical mirrors only if explicitly claimed on a trusted surface.

### 6. Crawl Limits

- MAX_HOPS from CP back to OP: default 3.
- MAX_OUTLINKS per page: default 50 (sorted by same‑site first, then by path depth).
- TIMEOUT per request: default 5s; MAX_CONTENT bytes: default 1 MiB; content sniffing only for textual types.
- Robots.txt: respect by default; provide `--ignore-robots` escape hatch for offline audits.

### 7. Scoring Function

Produce a scalar score in [0, 100] plus a classification label.

```
score = 60 * S + 30 * W + 10 * I - P
where
  S = min(1, strong_count / 1)           # strong saturates quickly
  W = min(1, weak_count   / 3)           # up to 3 weak signals
  I = min(1, indirect_count / 5)         # indirect helps but modestly
  P = penalties = 20 if any_untrusted_echo else 0
              + 10 * min(excess_hops, 3)
              + 10 if mixed_claims_detected else 0
```

- Labels: `score>=80 → "high"`, `50–79 → "medium"`, `<50 → "low"`.
- Emit per‑signal contributions in the evidence for auditability.

### 8. API

```python
from naive_backlink import crawl_and_score, EvidenceRecord, Result

res: Result = crawl_and_score(
    origin_url="https://pypi.org/project/foo/",
    trusted_overrides=["https://example.com"],
    blacklist_overrides=["https://libraries.io"],
    max_hops=3,
)
print(res.score, res.label)
for ev in res.evidence:
    print(ev.classification, ev.source.url, "→", ev.target.url)
```

Data classes (abridged):

```python
@dataclass
class Result:
    origin_url: str
    score: int
    label: Literal["high", "medium", "low"]
    evidence: list[EvidenceRecord]
    errors: list[str]
```

### 9. CLI

```
$ naive_backlink verify https://pypi.org/project/foo/
$ naive_backlink crawl https://pypi.org/project/foo/ --json out.json
$ naive_backlink print-evidence out.json --format markdown
```

Exit codes:

- `0`: completed; score computed; no network errors.
- `10`: completed with recoverable fetch/parse errors; score may be partial.
- `100`: no backlinks detected.
- `101`: only weak backlinks detected.
- `102`: only indirect backlinks detected.
- `>200`: usage or internal error.

### 10. Indirect Trails (Profile‑Only Paths)

Rules to accept OP → Repo → Profile → OP as *indirect*:

- Repo must be owned by the profile (API/HTML ownership cues).
- Profile page must include a link to OP or to a canonical personal domain that links to OP.
- Total hops ≤ MAX_HOPS.

### 11. Mirrors and Aggregators

- Pages whose purpose is bulk mirroring/aggregation (e.g., libraries.io project pages) MUST NOT contribute positive
  score. They MAY add a *penalty* if used as the sole backlink, to prevent false confidence via ubiquitous links.

### 12. Redirects and Shorteners

- Resolve up to MAX_REDIRECTS; accumulate `redirect` evidence. Final target classification determines signal strength.
  Shorteners contribute nothing by themselves.

### 13. Security and Abuse Considerations

- **Sybil pages**: Attackers can create look‑alike domains/profiles. Requiring at least one strong signal or multiple
  weak signals on trusted surfaces raises cost.
- **Unbounded crawling**: Enforce limits; refuse non‑text content types; avoid executing JS.
- **Privacy**: Store only minimal page snapshots and link metadata needed for audit. Respect robots.txt by default.

### 14. Backwards Compatibility

No impact on Python language semantics. The reference library introduces new CLI/API only.

### 15. Reference Implementation (RI)

- Pure‑Python, stdlib+`httpx`/`requests` optional; `lxml`/`html5lib` optional speedups.
- Deterministic configuration via `pyproject.toml` section:

```toml
[tool.naive_backlink]
max_hops = 3
trusted = ["mastodon.social", "github.com", "bsky.app", "gitlab.com", "bitbucket.org", "linkedin.com"]
blacklist = ["google.com", "bing.com", "duckduckgo.com", "libraries.io", "pastebin.com", "bit.ly", "t.co"]
```

### 16. Test Vectors

1. **Strong**: `OP: pypi.org/project/foo/` ↔ `mastodon.social/@alice` with `rel="me"` → score ≥ 80.
2. **Weak**: `OP` ↔ `github.com/alice/alice.github.io` README links back → score ~ 60–70.
3. **Indirect**: `OP` → `github.com/alice/foo` → `github.com/alice` → `OP` → score ~ 55–65.
4. **Aggregator only**: `OP` ↔ `libraries.io/...` → score < 50 with penalty.
5. **Mixed**: Strong + mirror noise → score ≥ 80 minus penalty.

### 17. Open Issues

- Platform‑specific verification semantics evolve (e.g., profile fields that are not linkified for some users). RI
  should keep a periodically updated site policy file.
- Disambiguation when multiple authors/maintainers present different identity trails.
- Federation edge cases (Mastodon instances with custom markup or rate limits).
- Handling content available only after authentication.

### 18. Rejected Ideas

- **Heavier ML classification**: Out of scope for initial RI; the goal is explainable signals.
- **Cryptographic proofs**: Excluded per non‑goals; separate PEP could specify sigstore/PGP integration.

### 19. Rationale

The design prioritizes explainability and auditability: every score component maps to explicit evidence items with
bounded crawl and conservative trust assumptions. `rel="me"` and profile backlinks are cheap to implement for
maintainers and harder to counterfeit at scale than mirror echoes.

### 20. References

- HTML `rel` values registry (`rel="me"`).
- Mastodon and ActivityPub conventions for verified links.
- Prior art: IndieWeb identity linking; GitHub profile website field; PyPI project metadata fields.

