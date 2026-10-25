# spotifactory.com

The website is the static page in `site/`: `index.html`, the favicon, the
link-preview image (`og.png`) and the setup-portal screenshot. There is no
build step.

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

Ink `#191414`, green `#1DB96E` (on light backgrounds `#128A52`). The green is
deliberately a little off Spotify's own brand green.
