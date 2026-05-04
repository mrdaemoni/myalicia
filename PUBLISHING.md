# Publishing to PyPI

This document is the playbook for releasing `myalicia` to PyPI so that `pip install myalicia` works for the world.

## One-time setup (do this once, takes 5 minutes)

### 1. Create a PyPI account

If you don't have one: [pypi.org/account/register](https://pypi.org/account/register/). You'll need to verify the email and (recommended) enable 2FA.

### 2. Reserve the project name

Until your first publish lands, the name `myalicia` is unclaimed and any other developer could take it. Reserve it by configuring a Trusted Publisher (this also avoids needing to store any API token in the repo).

1. Go to [pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/)
2. Scroll to "Add a new pending publisher"
3. Fill in:
   - **PyPI project name**: `myalicia`
   - **Owner**: `mrdaemoni`
   - **Repository name**: `myalicia`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`
4. Click **Add**

PyPI now trusts the GitHub Action defined at `.github/workflows/publish.yml` to publish to the `myalicia` project. No tokens or passwords stored anywhere.

### 3. Configure the GitHub environment

GitHub also needs to know about the `pypi` environment so the workflow can target it:

1. Go to [github.com/mrdaemoni/myalicia/settings/environments](https://github.com/mrdaemoni/myalicia/settings/environments)
2. Click **New environment**
3. Name it `pypi` (must match the workflow)
4. Optionally: add a "Required reviewer" so a release requires your manual approval before publish (recommended)
5. Save

That's it for setup. From here, every release is one tag push.

## Releasing a version

When you're ready to publish a new release:

### 1. Update the version

Edit two files:

- `pyproject.toml`: change `version = "0.1.0"` to the new version
- `myalicia/__init__.py`: change `__version__ = "0.1.0"` to match
- `CHANGELOG.md`: add a new entry for the version

### 2. Commit and push

```bash
git add -A
git commit -m "Release v0.1.0"
git push
```

### 3. Tag and push the tag

```bash
git tag v0.1.0
git push --tags
```

The `.github/workflows/publish.yml` workflow triggers on the tag push. It will:

1. Build sdist + wheel
2. Upload to PyPI (no token needed thanks to Trusted Publisher)
3. Create a GitHub Release with the artifacts attached

After ~30 seconds, `pip install myalicia` works for everyone.

### 4. Verify

```bash
pip install --upgrade myalicia
myalicia version
```

Should print the new version.

## Releasing a pre-release

For betas / alphas (like a v0.2.0-alpha to test the runtime split before final v0.2.0):

```bash
git tag v0.2.0a1
git push --tags
```

PyPI recognizes `a1` (alpha 1), `b1` (beta), `rc1` (release candidate) suffixes. Users can install with `pip install --pre myalicia`.

## If something goes wrong

### Build fails

Check the GitHub Actions run for the error. Most common: a syntax error introduced by the version bump, or a missing file in `[tool.setuptools.packages.find]`.

### Upload rejected

If PyPI rejects with "version already exists" — you can't re-upload the same version. Bump the version (e.g., `0.1.0` → `0.1.1`) and re-tag.

### Trusted Publisher issues

If the workflow fails on the publish step with "OIDC token rejected", check:
- The PyPI Trusted Publisher config matches the workflow filename, environment name, and repo name exactly
- The GitHub environment named `pypi` exists and has the right protection rules

### Releases that should never be public

If you accidentally tag a version that shouldn't be public:

```bash
# Delete the tag locally and on the remote
git tag -d v0.1.0
git push --delete origin v0.1.0
```

This won't recover what's already on PyPI. PyPI deletions are irreversible — you can yank a release (`pip` won't auto-install a yanked version) but it stays visible. Be careful with tag pushes.

## Sane defaults already in place

- `pyproject.toml` is configured with all required metadata
- `myalicia/defaults.yaml` is included via `[tool.setuptools.package-data]`
- The CI workflow builds and verifies installs on every PR (catches packaging regressions before release)
- The publish workflow waits on `build` succeeding before attempting publish

You should never need to run `python -m build` or `twine upload` locally. Tag → push → done.
