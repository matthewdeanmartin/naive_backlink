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

## Prior Art

- [mf2py](https://github.com/microformats/mf2py) Parse microformats from html. Only works if people actually used microformats.
- [Sherlock](https://github.com/sherlock-project/sherlock/tree/master) Doesn't claim people with same user name are the
  same people, but you know you were suspecting it.