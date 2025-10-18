# naive_backlink

Uncoordinated, accidental identity and trust. Because Alice and Bob are foreign state actors and this is better than
nothing.

## Installation

As CLI

```bash
pipx install naive-backlink
```

## Usage

Can be used as CLI tool, but was developed as a library for a larger tool.

Fastest is to only scan for well known ID sites and to only use XFN style `rel="me"` links. This is also incredibly
limited, but it is least likely to report something wrong.

- few websites have public profiles of large numbers of people
- fewer of these sites allow for posting links
- fewer of those allow including a `rel="me"` attribute or automatically include one

Most people didn't setup their online presence so that it would validate with this tool. For that, run with default
blacklists. In relaxed mode, indirect links are crawled for backlinks, so that my blog, which links to my social media,
which links to my github will show as one identity. `rel="me"` links are shown as strong links.

These nets are good enough for some scenarios, but not all, think it through.

See config example for

```
usage: naive_backlink verify [-h] [--links-file FILEPATH] [--only-well-known-id-sites] [--only-rel-me] url

positional arguments:
  url                   The origin URL to start crawling from.

options:
  -h, --help            show this help message and exit
  --links-file FILEPATH
                        A file containing a list of candidate URLs to check, one per line.

policy arguments:
  --only-well-known-id-sites
                        Only crawl URLs matching the built-in 'whitelist'. (Default: use blacklist)
  --only-rel-me         Only respect links explicitly marked with rel="me" as evidence.
```

## Example run

```text
Verifying backlinks for: https://blog.wakayos.com/...

Score: 85 (high)

--- Evidence Found ---
- [STRONG  ] on: http://mastodon.social/@mistersql
- [STRONG  ] on: https://github.com/matthewdeanmartin
- [STRONG  ] on: https://mastodon.social/users/mistersql
...
- [STRONG  ] on: https://mastodon.social/@mistersql
...

--- Link Graph ---
https://blog.wakayos.com
├─ http://mastodon.social/@mistersql  [direct]
├─ https://github.com/matthewdeanmartin  [direct]
...
├─ https://mastodon.social/@mistersql  [direct]
├─ https://mastodon.social/users/mistersql  [direct]

```

## Reasoning

Not all pages feel like "identity" pages. User profile pages of certain website do feel like identity pages. There
are a limited number of these sites, fewer with a large user base, fewer that allow posting backlinks and even fewer
that allow posting links with custom attributes in the backlink. So we can't rely entirely on "XFN rel=me" style
backlinks.

- Strong links use XFN rel=me or a platforms idiosyncratic claim, often via oidc/oauth between sites.
- A weak backlink is just a backlink without an additional signs that the user intended it to mean identity. Maybe it is
  a link between mutual work colleagues.
- A backlink is often part of a graph, creating indirect backlinks, a & c backlink via b, in a-b-c
- Some links can be claimed but can't be verified by crawling because of anti-crawler limits, so linkedin.com links
  can't be verified, but they can be listed when found.
- Some identity sites are too valuable to not crawl even if they're locked behind API

## Hypothetical Trust  Attacks

- A user wants to publish a package and gain trust. They create accounts on linkedIn, mastodon.social and pypi and cross
  link all these pages. These probably are low quality, low effort, profiles and are dodgy looking if a human looked it
  them. Defense would be to figure out how to evaluate the reputation and effort of a profile at an identity site.
- Next attack is same as first, except the accounts are created, then you wait five years, and now the linked accounts
  don't feel dodgy because they were all created on the same day.
- A user wants to publish a package and gain trust. So he links it back to celebrity John Doe. John Doe is unaware of
  this so has no backlinks, but does have links to blogs. So the hacker adds comments on the blog with URLs to and from
  John Doe's page and the pypi package, creating an indirect link. The mitigation is to only use rel=me or to only use
  identity sites, since a blog (other than the profile page) isn't an identity site.
- A user wants to publish a package and gain trust. Since they know they're malicious, the best lie is a simple lie,
  that they are lazy and can't be bothered to link to anything, like many other packages.

## Prior Art

- [mf2py](https://github.com/microformats/mf2py) Parse microformats from html. Only works if people actually used
  microformats.
- [Sherlock](https://github.com/sherlock-project/sherlock/tree/master) Doesn't claim people with same user name are the
  same people, but you know you were suspecting it.