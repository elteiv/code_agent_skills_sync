# Python Skill Sync Hook

This workspace contains a standalone Python SessionStart hook script that downloads the latest skill files from a remote server into the current project.

## Files

- `sync_skills.py`: Fetches a manifest, downloads the referenced skill files, writes them into the project, and removes stale files from prior syncs.

## Remote Manifest Format

The script expects `SKILL_MANIFEST_URL` to return JSON with this shape:

```json
{
  "version": "2026-06-24",
  "baseUrl": "https://skills.example.com/",
  "skills": [
    {
      "path": "backend/observability/SKILL.md",
      "url": "/skills/backend/observability.md"
    },
    {
      "path": "frontend/design-system/SKILL.md",
      "inlineContent": "# Embedded skill\n..."
    }
  ]
}
```

Rules:

- `path` is the relative output path inside the local skills directory.
- Each skill entry must provide either `url` or `inlineContent`.
- Relative `url` values are resolved against `baseUrl` when present, otherwise against `SKILL_MANIFEST_URL`.

## Environment Variables

- `SKILL_MANIFEST_URL`: Required. HTTPS endpoint that returns the manifest JSON.
- `SKILL_API_TOKEN`: Optional bearer token for authenticated requests.
- `SKILL_DEST_DIR`: Optional output directory. Defaults to `.claude/skills`.
- `SKILL_SYNC_TIMEOUT_MS`: Optional request timeout in milliseconds. Defaults to `15000`.
- `SKILL_SYNC_INSECURE_TLS`: Optional. Set to `1` only if you must bypass TLS verification for an internal server.

## Local Run

```powershell
$env:SKILL_MANIFEST_URL = "https://skills.example.com/manifest.json"
python .\sync_skills.py
```

## Claude Code SessionStart Hook

Add the script to your Claude Code SessionStart hook and pass the manifest URL through environment variables. A representative hook command looks like this:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 sync_skills.py"
          }
        ]
      }
    ]
  },
  "env": {
     "SKILL_MANIFEST_URL": "https://{server}/manifest.json",
     "SKILL_API_TOKEN": "{API TOKEN}",
     "SKILL_DEST_DIR": ".claude/skills"
  }
}
```

Adjust the surrounding config shape to match the Claude Code configuration file you use in your environment. The important part is that SessionStart runs this script in the project root so the output lands in the current repository.

## Behavior

- Downloads the manifest on every session start.
- Writes only changed files by comparing content hashes.
- Tracks synced files in `.claude/skills/.sync-state.json`.
- Removes files that were managed previously but are no longer present in the latest manifest.