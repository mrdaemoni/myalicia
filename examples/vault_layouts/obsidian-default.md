# Obsidian vault layout — default

The vault layout My Alicia expects out of the box. If you have an existing Obsidian vault, you can either reshape it to match this, or override the layout in `~/.alicia/config.yaml` under `vault:`.

## Folder structure

```
{vault.root}/                    # your top-level vault, e.g. ~/Documents/my-vault
├── Books/                       # one note per book, with quotes & questions
├── People/                      # one note per person you write about
├── Daily/                       # daily logs (My Alicia writes here)
├── Captures/                    # quick ideas, drafts (you write here)
└── Alicia/                      # ⮕ My Alicia's working area
    ├── Bridge/                  # the surfacing queue between you and her
    │   ├── inbox.md             # things waiting for your attention
    │   └── surfacing_queue.jsonl
    ├── Wisdom/                  # synthesis output (Notice + Know loops)
    │   ├── Daily/
    │   ├── Weekly/
    │   └── Synthesis/           # cross-book / cross-time syntheses
    └── Self/                    # archetype + self-portrait data
        ├── archetype.md
        └── Profiles/            # weekly self-portraits (YYYY-WNN-*.md)
```

## What lives where

| Folder | Owner | Contents |
|---|---|---|
| `Books/` | you | book notes — quotes, questions, takeaways |
| `People/` | you | notes about people you think about |
| `Daily/` | both | day-stamped working files |
| `Captures/` | you | quick ideas before they're organized |
| `Alicia/Bridge/` | her | her queue of things to surface to you |
| `Alicia/Wisdom/` | her | her synthesis output, dated and themed |
| `Alicia/Self/` | her | her own archetype and self-portrait |

## Configuring a different layout

If your vault already has a different structure, override in `~/.alicia/config.yaml`:

```yaml
vault:
  root: ~/Documents/my-vault
  inner: AI                        # subfolder where My Alicia writes
  bridge: Inbox                    # rename the surfacing folder
  wisdom: Synthesis                # rename the synthesis folder
  self_dir: Profile                # rename the archetype folder
```

The skill modules read these via `config.vault.*_path` properties — no hardcoded folder names in the codebase.
