# GitHub setup — two repos, one walkthrough

You're shipping two separate things, so you need two separate repos:

| Folder | Repo | Domain |
|---|---|---|
| `~/Desktop/myalicia/` | `github.com/YOUR_USERNAME/myalicia` | the code |
| `~/Desktop/myalicia-site/` | `github.com/YOUR_USERNAME/myalicia-site` | myalicia.com |

Keeping them separate means the website can be deployed/redeployed without touching code, and the code can be released without touching the site.

---

## For each repo, the same five steps

### 1. Create the empty repo on GitHub

In your browser, go to **https://github.com/new**.

- **Repository name**: `myalicia` (then later, `myalicia-site`)
- **Description**: short, public-facing
- **Public** (for both — that's the whole point)
- **Do NOT** check "Add a README", "Add .gitignore", or "Choose a license" — we already have those locally and don't want GitHub creating duplicates we'd then have to merge.

Click **Create repository**. GitHub will show you a page with command-line instructions — keep it open as a reference.

### 2. Initialize git in your local folder

In Terminal:

```bash
cd ~/Desktop/myalicia
git init -b main
```

`-b main` sets the default branch name to `main` (GitHub's convention).

### 3. Stage and commit

```bash
git add -A
git commit -m "Initial commit"
```

### 4. Connect the local folder to the GitHub repo

Replace `YOUR_USERNAME` with your actual GitHub username:

```bash
git remote add origin https://github.com/YOUR_USERNAME/myalicia.git
```

### 5. Push

```bash
git push -u origin main
```

GitHub will prompt for your username and a personal access token (or use the GitHub CLI / SSH if you have those set up). The `-u` flag tells git to remember this remote/branch pairing so future pushes are just `git push`.

---

## Then repeat for the site

```bash
cd ~/Desktop/myalicia-site
git init -b main
git add -A
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/myalicia-site.git
git push -u origin main
```

---

## After both are pushed

A few small follow-ups worth doing once:

- **Update placeholder URLs.** A few files reference `https://github.com/YOUR_USERNAME/myalicia` — replace with your actual username:
  - `~/Desktop/myalicia/README.md`
  - `~/Desktop/myalicia-site/src/layouts/Base.astro`
  - `~/Desktop/myalicia-site/src/pages/index.astro`
  - `~/Desktop/myalicia-site/README.md`

- **Add a description and topics on GitHub.** Each repo's GitHub page has a small "About" gear in the top right — add a one-line description, the website URL (myalicia.com once it's deployed), and topics like `agent`, `humorphism`, `obsidian`, `python`.

- **Deploy the site.** Connect the `myalicia-site` repo to [Netlify](https://app.netlify.com/) or [Cloudflare Pages](https://pages.cloudflare.com/) — both have a "Connect to GitHub" flow that auto-deploys on every push. After that, point myalicia.com at the deploy via your domain registrar's DNS settings.

---

## If something goes wrong

The most common first-push errors:

- **`error: src refspec main does not match any`** — you forgot to commit (`git commit -m "..."`) before pushing.
- **`failed to push some refs`** — the remote already has commits (probably because you accidentally checked the README/license box on GitHub). Run `git pull --rebase origin main` then `git push`.
- **`Authentication failed`** — GitHub no longer accepts plain passwords. Use a [personal access token](https://github.com/settings/tokens) as the password, or set up the [GitHub CLI](https://cli.github.com/) (`gh auth login`) which handles auth for you.
