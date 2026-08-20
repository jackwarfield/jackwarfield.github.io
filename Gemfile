# For previewing the site locally.
#
# GitHub Pages does not read this file -- it builds with its own pinned Jekyll.
# This deliberately does NOT use the `github-pages` gem: that gem pins Jekyll
# 3.9, which is from 2020 and does not run on a current Ruby. This site uses no
# plugins and only standard Liquid filters, so Jekyll 4 renders it identically
# to what GitHub Pages produces.

source "https://rubygems.org"

gem "jekyll", "~> 4.3"
gem "kramdown-parser-gfm"   # kramdown 2 split GFM out into its own gem

# Ruby moved these out of the standard library. Jekyll needs them, and which
# ones are missing depends on your Ruby version, so declare them all.
gem "webrick"
gem "csv"
gem "base64"
gem "bigdecimal"
gem "logger"
gem "ostruct"
