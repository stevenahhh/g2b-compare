# Bundled seed database

`seed.sqlite3` is generated from the approved populated local database by
`desktop/scripts/prepare-seed.ps1`. It is a local release input and is never
listed as a Tauri resource. `desktop/scripts/tauri.ps1` hashes it with
permissive sharing, then atomically writes the deterministic
`seed.sqlite3.zip` resource and its source-hash metadata when it changes.
Both generated files are intentionally ignored by Git.

The preparation script removes estimate drafts, lines, and comparisons before
the database enters a desktop installer. It never writes to the source
database. At first startup the desktop app validates and extracts the single
archive entry into the user data directory under its existing bootstrap lock.
