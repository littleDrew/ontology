# Skill Distribution Notes

This folder is only for optional, locally generated packaging artifacts.

## Canonical installation guide
To avoid duplicated instructions, use this as the single source of truth:
- `skills/software-system-research-and-design/references/installation-and-evaluation.md`

## Purpose of this folder
- Hold temporary build outputs such as `*.skill`.
- Do **not** treat packaged artifacts as source-of-truth.

The source-of-truth is always:
- `skills/software-system-research-and-design/SKILL.md`
- `skills/software-system-research-and-design/references/`

## Optional local packaging shortcut
If you only need to generate a local package quickly:

```bash
python3 /opt/codex/skills/.system/skill-creator/scripts/package_skill.py \
  skills/software-system-research-and-design \
  skills/dist
```

Do not commit generated `.skill` files to this repository.
