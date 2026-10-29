# spotifactory.com

The website is the static pages in `site/`: the home page (`index.html`),
`why-spotify.html` (served at /why-spotify), `build.html` (served at /build)
and their shared `style.css`, plus the favicon, the link-preview image
(`og.png`) and the setup-portal screenshot. There is no build step: Cloudflare
Pages serves `/build` from `build.html` on its own.

## Case files and screen images

The build guide links the case STLs, a zip of them, and the two case renders
straight from the rolling **case-files** GitHub release
(`https://github.com/peasus/spotifactory/releases/download/case-files/<file>`).
The `Case files` workflow (`.github/workflows/case-files.yml`) rebuilds them
from `enclosure/easel.py` and re-uploads them whenever `enclosure/` changes on
`main`, so nothing in `site/` needs regenerating. To rebuild by hand, run the
workflow from the Actions tab.

`site/img/oled-*.png` are the home screen drawn with the app's own layout and
icons, so redo them if the now-playing screen changes.

## Stylesheet version

The pages link `/style.css?v=<hash>` so browsers (iPhone Safari especially)
never pair a new page with an old cached stylesheet. After changing
`site/style.css`, update the hash in all three pages:

```sh
H=$(sha1sum site/style.css | cut -c1-8)
sed -i -E "s#/style.css(\?v=[0-9a-f]+)?\"#/style.css?v=$H\"#" site/*.html
```

## Hosting (Cloudflare Pages, free tier)

One-time setup in the Cloudflare dashboard:

1. **Workers & Pages → Create → Pages → Connect to Git**, and pick
   `peasus/spotifactory`.
2. Production branch: `main`. Framework preset: **None**. Build command:
   leave empty. Build output directory: `site`.
3. Under **Settings → Build → Build watch paths**, include `site/*` so code
   changes elsewhere in the repo don't redeploy the site.
4. **Custom domains → Set up a domain**: add `spotifactory.com`, then
   `www.spotifactory.com`. If the domain's DNS is already on Cloudflare the
   records are created for you; otherwise Cloudflare shows the CNAME to add.

After that, every merge to `main` that touches `site/` publishes the page,
and each pull request gets its own preview URL.

## Linking it from GitHub

- Repo: on the repository page, the gear next to **About** → Website:
  `https://spotifactory.com`.
- Profile: **Edit profile** → Website: `https://spotifactory.com`, and pin the
  repository under **Customize your pins**.

## Colours

Ink `#191414` and avocado chartreuse `#A9C23F` (on light backgrounds
`#5C6B1C`). The accent was moved off Spotify's brand green on purpose.
