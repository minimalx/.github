# MinimalX `.github` — Workflow Templates & Shared Actions

Lightweight, reusable GitHub Actions for MinimalX repos. This repo is consumed as a **submodule** named `workflow-templates` and provides **composite actions** and **starter workflow templates**.

---

## How to use

1. **Add as submodule (once per repo)**

```bash
git submodule add -b main --name workflow-templates git@github.com:minimalx/.github.git workflow-templates
git submodule update --init --recursive
```

2. **Call the composites in your workflow**
   Create `.github/workflows/ci.yml` in your project:

```yaml
name: CI

env:
  VERSION_ACTION: &VERSION_ACTION ./workflow-templates/actions/version
  FORMATTING_ACTION: &FORMATTING_ACTION ./workflow-templates/actions/formatting
  BUILD_ACTION: &BUILD_ACTION ./workflow-templates/actions/build_vesc

on:
  pull_request:
    branches: [ $default-branch ]
  push:
    branches: [ $default-branch ]

jobs:
  version:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.ver.outputs.version }}
      version_tag: ${{ steps.ver.outputs.version_tag }}
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0, submodules: recursive }
      - id: ver
        uses: *VERSION_ACTION
        with: { tag-prefix: "v" }

  formatting:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0, submodules: recursive }
      - uses: *FORMATTING_ACTION
        with:
          base-ref: ${{ github.event_name == 'pull_request' && github.base_ref || 'main' }}
          changed-exts: "c,cc,cpp,h,proto"

  tag:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    needs: [version, formatting]
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@v4
      - run: |
          git config --local user.email "action@github.com"
          git config --local user.name  "GitHub Action"
          git tag -a "${{ needs.version.outputs.version_tag }}" -m "Release ${{ needs.version.outputs.version_tag }}"
          git push origin "${{ needs.version.outputs.version_tag }}"
```

> **Important:** You must run `actions/checkout` with `submodules: recursive` in each job that uses local actions from this submodule.

3. **Update to latest templates**

```bash
git submodule update --remote --merge workflow-templates
git add workflow-templates && git commit -m "chore: bump workflow-templates"
```

---

## Repo structure

```
workflow-templates/        # submodule root inside consumer repos
├─ actions/
│  ├─ version/             # semver + version.h
│  │  ├─ action.yml
│  │  └─ generate_version_h.py
│  ├─ formatting/          # clang-format check
│  │  ├─ action.yml
│  │  └─ formatting_check.py
│  └─ build_vesc/          # build + artifact upload
│     └─ action.yml
└─ workflow-templates/     # starter CI workflow(s)
   ├─ c-projects-minimal-org-ci.yml
   └─ *.properties.json / assets
```

**Conventions**

* Composite actions live under `actions/<name>/action.yml`.
* Helper scripts sit next to their composite and are referenced via `${GITHUB_ACTION_PATH}`.
* Starter workflows are examples you can copy or adapt.

---

## Available actions (brief)

* **`actions/version`** → outputs `version`, `version_tag`, generates `version.h` (uses `paulhatch/semantic-version@v5`).
* **`actions/formatting`** → installs `clang-format-20` and checks changed files (`--dry-run --Werror`).
* **`actions/build_vesc`** → runs make targets, renames `.bin/.elf` with `v<version>`, uploads artifacts.

Pin third‑party actions where practical.

---

## Contributing

1. **Create a composite** in `actions/<name>/` with `action.yml` (composite) and optional helpers.
2. **Keep shell installs in YAML**, keep Python focused on logic.
3. **Test locally** by referencing it via the submodule in a sandbox repo.
4. **Docs**: update this README and/or add a short `README.md` in your action folder.
5. **Backwards‑compat**: avoid breaking input/output names; when needed, add new ones and deprecate old.

**PR checklist**

* [ ] Action folder + `action.yml` present
* [ ] Uses `${GITHUB_ACTION_PATH}` for local scripts
* [ ] Minimal permissions; pin external actions where feasible
* [ ] Example snippet added under `workflow-templates/` if applicable

---

## Troubleshooting

* **Action not found / no action.yml** → Ensure job ran `actions/checkout@v4` with `submodules: recursive`.
* **Expressions in `uses:`** → Not supported. Use YAML anchors for reusable paths.
* **`$ACTIONS_PATH` empty** → Use `${GITHUB_ACTION_PATH}` inside composites.
* **`github.base_ref` empty on push** → Default to `main` in formatting.

---

## License & ownership

* Owned by MinimalX Platform team. Open PRs/issues for improvements.
* Code follows repo LICENSE (see root).
