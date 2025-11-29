# TODO

## Constrain What Pages are Profiles

Whitelist identity sources

Sites with Identity where the identity has some social validity (how they got that we don't know!) 
- mastodon.social, github.com = identity. 
- But some random site, nope. Rules out custom domains

Good Qualities of Identity site
- Has authentication (not pastebin)
- Has publicly available profile pages
- User can post to profile page
- Other users cannot post to profile page (blogs with comments not so good here)
- Identities can't be transferred and don't expire (old twitter)
- Links are to self, not to friends or just other info (like tree, keybase, liberapay)

Sites with "prove my identity elsewhere"
- https://keybase.io/matthewmartin - post a cryptographic string on other site which first site queries for proof.
- https://liberapay.com/matthewdeanmartin/  - oauth, site 1 is oauth app of site 2

API-only sites, Paid access only, etc.
- reddit.com
- twitter.com
- linkedin.com



## TODO

Disable links to own domain (github.com/xyz to github.com/abc)
Disable links to own subdomain (github.com/xyz to gist.github.com)
Tree of links - Mostly implemented!

```
Pypi (root)
    - github
        - blog
    - docs
        - social media
            - other social media
     - dev.to (   <a href="https://github.com/matthewdeanmartin" target="_blank" rel="noopener me ugc" class="profile-header__meta__item"> )  
            
```

Option to favor identity websites.

Event supports rel-me
-----
GitHub — user profiles like github.com/username.
Mastodon (fediverse) — e.g. mastodon.social/@username.
Keybase — keybase.io/username.
Gravatar — gravatar.com/username. It offers profile data in JSON/XML etc. (I think?)
Wikipedia - https://en.wikipedia.org/wiki/User:Matthewdeanmartin  (suppors rel=me via "URLs to external profiles:")
Wikipedia / Wikidata may count: pages like en.wikipedia.org/wiki/User:Username.
Dev.to — dev.to/matthewdeanmartin.
GitLab — gitlab.com/username -- need to check
Bitbucket — bitbucket.org/username

CURL BLOCKED
-----
LinkedIn — linkedin.com/in/username. (You noted problems fetching via API / heavy wall.)
Twitter (now “X”) — twitter.com/username. The API is available (with auth) for user lookup.
Instagram — instagram.com/username. (But extracting links + metadata may be harder due to API restrictions / private vs public).
YouTube — user channels / handles: youtube.com/@username or youtube.com/user/username etc.
Reddit — reddit.com/user/username.
Medium — medium.com/@username.

Has User Profile Page, but no rel=me
---
Stack Overflow / Stack Exchange — user profiles like stackoverflow.com/users/<id>/username.

## Hosted blogs
Tumblr — username.tumblr.com (if still active).

## Profile but what use is it for pypi package trust graphs?
Goodreads — goodreads.com/user/show/<id>-username.
OpenStreetMap — openstreetmap.org/user/username.
Flickr — flickr.com/people/username (or numeric id).
SoundCloud — soundcloud.com/username.
Vimeo — vimeo.com/username.
500px (photo site) — 500px.com/username.
Dribbble — dribbble.com/username -- UI design


## Money or patially money sites
Patreon — patreon.com/username.
Twitch — twitch.tv/username.
Behance — behance.net/username  -- freelancer site

## Is specifically for listing profiles
linktr.ee - no rel=me support?


## Too many backlinks!

- gravatar self links to same page in every language with a subdomain
- many links on same domain because it is in a header
- many links, but with a `?querystring` but it is all the same profile page

## Double query?

- When to disable playwright?
- Does it always need to run?

## Crawl blockers

- reddit.com
- linkedin.com
- pypi.com
- youtube.com (?)

## bug
- fails to crawl example.com, but will crawl https://example.com

## JSON, XML, ETC Crawlers

- pypi - blocked except via json
- mastodon - uncertain if blocked or not, API available
- github - generally not blocked
- twitter - blocked, very limited free API