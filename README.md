# jackwarfield.com

Personal site, built with [Jekyll](https://jekyllrb.com/) and served by GitHub
Pages from the `master` branch. Push to `master` and the live site rebuilds in a
minute or two.

---

## How to update things

Almost nothing on this site requires editing HTML. The content lives in
`_config.yml` and in three data files under `_data/`.

| I want to change… | Edit this |
| --- | --- |
| Name, title, affiliation, email, photo, CV file, nav menu | `_config.yml` |
| A publication | `_data/publications.yml` |
| A research project | `_data/research.yml` |
| A link on the *Other pages* page | `_data/links.yml` |
| The About page prose | `about/index.html` |
| Colours, spacing, type | the tokens at the top of `css/main.css` |

### Adding a publication

Either add it by hand to `_data/publications.yml` (copy an existing block; the
file's header comment lists every field), or let ADS fill it in:

```bash
export ADS_API_TOKEN="..."          # once; get one at
                                    # https://ui.adsabs.harvard.edu/user/settings/token

python3 scripts/add_publication.py 2025arXiv251024849W --category first
python3 scripts/add_publication.py arXiv:2510.24849 --dry-run   # preview only
```

The script accepts a bibcode, an arXiv ID, or a DOI. Categories are `first`,
`observing`, and `other`; they are defined at the top of
`_data/publications.yml`, and you can add more there.

Your own name is bolded automatically in every author list — that is the
`author_highlight` setting in `_config.yml`.

### Catching up with ADS

To find everything of yours on ADS that is not yet on the site:

```bash
python3 scripts/add_publication.py --jack
```

It queries ADS for your papers, works out which are missing from
`_data/publications.yml`, and walks you through them one at a time:

```
[1/2]  2026   arXiv:2601.01234
    Proper Motions of M31 Satellites with JWST
    J. T. Warfield, N. Kallivayalil, S. T. Sohn, et al.
    [1] first  [2] observing  [3] other   [s]kip  [q]uit >
```

The category menu is built from whatever is listed at the top of
`publications.yml`, so adding a category there makes it an option here. Each
paper you accept is inserted at the **top** of its category, which is where a
new one belongs. `s` skips, `q` stops and keeps what you have accepted so far.

`--jack -n` lists what is missing without prompting. Conference abstracts are
hidden by default — ADS indexes every AAS meeting abstract and they drown out
the papers — and the count of hidden ones is always printed; `--all-doctypes`
includes them.

Papers already in the file are recognised even when the file stores an old
arXiv bibcode and ADS has since published the paper under a new one, so
nothing gets offered to you twice.

Who "--jack" means is the `ME` line near the top of the script. Edit it if your
name is indexed differently on ADS, or to change the year range.

### Keeping preprints current

Preprints get a new bibcode when they are published, and the volume and page
numbers only exist once the paper is out. To reconcile the file with ADS:

```bash
python3 scripts/add_publication.py --refresh           # report what is stale
python3 scripts/add_publication.py --refresh --write   # apply it
```

`--write` updates the bibcode, journal, volume, and page, drops the `status:`
badge once a paper is published, and fills in the DOI and arXiv number if they
were missing. It touches only the fields that actually changed and leaves your
`links:`, `category:`, and author lists alone. Run it without `--write` first —
it prints exactly what it would do.

Note that this looks records up by `identifier:`, not `bibcode:`. That matters:
ADS's `bibcode:` field matches only a record's *canonical* bibcode, so an arXiv
bibcode whose paper has since been published matches nothing at all — which is
the entire set of entries this command is meant to find.

### Updating the CV

Drop the new PDF in `docs/` and change the `cv:` line in `_config.yml`. The nav
menu also has the path in it (under `nav:`), so update both.

---

## Previewing locally

```bash
bundle install                # first time only
bundle exec jekyll serve      # then open http://localhost:4000
```

Edits to pages and data files show up on refresh. Edits to `_config.yml` do
**not** — restart the server after changing it.

If you do not have Ruby set up, the fastest route on macOS is:

```bash
brew install ruby chruby ruby-install
gem install bundler
```

---

## Layout of the repo

```
_config.yml            site-wide settings; the nav menu lives here
_data/                 all page content that is a list of things
  publications.yml
  research.yml
  links.yml
_includes/             head, header, footer — shared by every page
_layouts/              default (page shell), page (with a title block), post
css/main.css           one stylesheet; design tokens are at the top
scripts/               helper scripts, not published with the site
docs/                  the CV PDF
images/
index.html             home page
about/  research/  publications/  otherpages/  blog/
cv/  links/            redirects kept for old bookmarks
404.html
```

The site uses no Jekyll plugins beyond what GitHub Pages runs by default, and no
external fonts, JavaScript libraries, or CDN requests — so it stays fast and
nothing can break from the outside.
