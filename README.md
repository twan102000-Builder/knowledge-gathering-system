# Knowledge Gathering System (KGS) — Unified Local Repository

A unified, zero-local-disk-bloat knowledge gathering engine. Integrates clipboard snippet ingestion, automated SD card/removable media importing, web document conversion (.md, .txt, .pdf, .epub), Dewey-style taxonomy management, SHA-256 integrity manifests, and an offline searchable catalog.

All content is staged locally in temporary memory/disk (`/tmp/knowrepo_stage`), verified via SHA-256, and immediately flushed to the portable drive (`~/KnowRepo1` -> `/mnt/shared/removable/USB Drive`), leaving zero clutter on the host device.

---

## Repository Taxonomy on Attached Drive (`~/KnowRepo1`)

```
~/KnowRepo1/
├── 00_Index_and_Manifests/
│   ├── INDEX.md             # Master Markdown index
│   ├── index.html           # Offline interactive searchable catalog
│   ├── MANIFEST.sha256      # SHA-256 hashes for corruption/bit-rot detection
│   ├── catalog.json         # Machine-readable registry
│   └── kgs_metadata.db      # SQLite query database
├── 01_Medical_and_Health/
├── 02_Survival_and_Food/
├── 03_Engineering_and_Repair/
├── 04_Science_and_Reference/
├── 05_Computing_and_Comms/
├── 06_History_Law_and_Civics/
└── 07_Uncategorized_Inbox/
    ├── snippets/            # Captured text/code clips
    ├── media/               # Screenshots/images
    └── sd_imports/          # Dumped/synced SD card content
```

---

## Unified Command Suite (`src/cli.py`)

### 1. Web Source Ingestion
Downloads, converts to clean `.md`/`.txt` or saves native `.pdf`/`.epub`, computes checksums, moves to category on `~/KnowRepo1`, and cleans staging:
```bash
# Ingest an article or guide into Category 01 (Medical) as Markdown
python3 src/cli.py ingest "https://example.com/field-first-aid" -c 01 -f md -t "Field First Aid Guide"

# Download a technical manual into Category 03 (Engineering) as PDF
python3 src/cli.py ingest "https://example.com/solar-inverter-wiring.pdf" -c 03 -f pdf

# Auto-detect format and save to Category 05 (Computing)
python3 src/cli.py ingest "https://example.com/linux-networking" -c 05
```

### 2. Clipboard Aggregator
```bash
# Capture current clipboard selection
python3 src/cli.py clip

# Capture with tags and citation notes
python3 src/cli.py clip --tag "medicine,surgery" --note "Emergency wound closure technique"

# Run background clipboard watcher daemon
python3 src/cli.py clipboard-watch --interval 1.0
```

### 3. SD Port & Removable Media Ingest
```bash
# List all connected SD cards / flash media
python3 src/cli.py sd list

# Safely mount read-only, hash-deduplicate, and copy into vault
python3 src/cli.py sd import --device auto

# Safely unmount and eject SD card
python3 src/cli.py sd eject /dev/mmcblk0p1
```

### 4. Integrity, Indexing & Search
```bash
# Rebuild master INDEX.md, index.html, and MANIFEST.sha256
python3 src/cli.py index

# Verify bit-rot and file integrity on attached drive
python3 src/cli.py verify

# View overall repository status
python3 src/cli.py status

# Search across all ingested items and tags
python3 src/cli.py search "first aid"
```

---

## SD Card Provisioning, Media Replication & Multi-Device Deployment

Detailed hardware provisioning, partition/filesystem preparation (exFAT/ext4), ChromeOS passthrough, replication procedures, and client setup instructions are documented in:
- **[KnowRepo1 Complete Source Duplication & Replication Reference Manual](docs/KNOREPO1_DUPLICATION_AND_REPLICATION_REFERENCE_MANUAL.md)**
- **[SD Card Provisioning & Removable Storage Guide](docs/SD_CARD_PROVISIONING_AND_STORAGE_GUIDE.md)**

### Media Duplication Utility (`duplicate_repo.py`)
To clone the complete repository from the primary drive (`KnowRepo1`) to a secondary SD card (`KnowRepo2`) or external vault with high-speed 16MB buffered transfers and post-copy verification:
```bash
# Duplicate KnowRepo1 to KnowRepo2 (default)
python3 duplicate_repo.py

# Custom source/destination replication
python3 duplicate_repo.py --src /path/to/source --dst /path/to/destination --buffer-mb 16

# Verification audit only
python3 duplicate_repo.py --verify-only --src ~/KnowRepo1 --dst ~/KnowRepo2
```

### Multi-Device Client Access
- **Offline Browser**: Open `00_Index_and_Manifests/index.html` on any device without internet connection.
- **Kiwix Reader**: Open `.zim` archives in `04_Science_and_Reference` & `06_History_Law_and_Civics` using Kiwix (Android, iOS, Windows, macOS, Linux).
- **Local Network Wi-Fi Hotspot**: Host catalog with `cd 00_Index_and_Manifests && python3 -m http.server 8080`.

