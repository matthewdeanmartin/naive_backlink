#!/bin/bash
set -eou pipefail

naive_backlink --verbose verify --links-file pypi_links.txt "https://pypi.org/project/troml-dev-status/"
naive_backlink --verbose verify "https://github.com/matthewdeanmartin/" #
naive_backlink --verbose verify "https://keybase.io/matthewmartin" # 2 backlinks found!
naive_backlink --verbose verify "https://mastodon.social/@mistersql"
naive_backlink --verbos everify "https://blog.wakayos.com/"
