# naive_backlink
Uncoordinated, accidental identity and trust. Because Alice and Bob are foreign state actors and this is better than nothing..


## Example run


```text
naive_backlink on  main [!+?] is 📦 v0.1.0 via 🐍 v3.14.0 (naive-backlink) 
❯ ./test.sh
Verifying backlinks for: https://pypi.org/project/troml-dev-status/...
WARNING: Found links, but no backlinks to origin on candidate page: https://github.com/matthewdeanmartin
WARNING: Found potential backlink from https://github.com/matthewdeanmartin/troml_dev_status to origin!
WARNING: Found links, but no backlinks to origin on candidate page: https://libraries.io/pypi/troml_dev_status
WARNING: Found links, but no backlinks to origin on candidate page: https://security.snyk.io/package/pip/troml_dev_status

Score: 25 (low)

--- Evidence Found ---
- [WEAK  ] Backlink found on page: https://github.com/matthewdeanmartin/troml_dev_status
```