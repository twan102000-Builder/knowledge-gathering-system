# Knowledge Gathering System (KGS) — Unified Local Repository

A unified, zero-local-disk-bloat knowledge gathering engine. Integrates clipboard snippet ingestion, automated SD card/removable media importing, web document conversion (.md, .txt, .pdf, .epub), deduplication, metadata indexing, and dual-tier synchronization across local machines and a shared portable archive drive.

KGS features a Dual-Tier Storage Architecture optimized for Apple macOS devices and portable removable archive drives of varying capacities (for example USB-C SSDs and HDDs from smaller external drives to multi-terabyte devices). Ingest and search locally on Mac with zero latency, then push verified content to a shared archive partition that is identified by label and mount metadata rather than by a fixed 1 TB assumption.

---

## Cross-Device Architecture (Mac mini, MacBook Pro, Portable Archive Drive)

```
+---------------------------------------------------------------------------------------------------+
|                                      CROSS-DEVICE ECOSYSTEM                                       |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [Device A: Mac mini Workstation]                    [Device B: MacBook Pro (Mobile)]             |
|   • Main Storage: Samsung 990 PRO NVMe                • Main Storage: Internal NVMe SSD           |
|   • Local Repo  : /Volumes/990_PRO/KnowRepo_Local     • Local Repo  : ~/KnowRepo_Local            |
|   • Fast local NVMe capture & offline search          • Fast mobile capture & field reading       |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
                                           |                                           |
                                           | USB-C (when connected)                    | USB-C (when connected)
                                           +---------------------+---------------------+
                                                                 |
                                                                 v
                                  +-------------------------------------------------------------+
                                  | [UNIVERSAL MAIN KNOW REPO ARCHIVE]                           |
                                  | Portable removable archive drive (capacity varies by device) |
                                  |                                                             |
                                  |   Single dedicated KnowRepo partition                       |
                                  |   • Holds the canonical master repository, manifests,       |
                                  |     Dewey categories (00-07), and metadata database         |
                                  |   • Shared across Mac mini, MacBook Pro, and all devices    |
                                  |   • Sibling partitions are preserved untouched               |
                                  +-------------------------------------------------------------+
```

### Repository Taxonomy (`00` to `07`)

```
KnowRepo_Vault/
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

### 1. Dual-Tier Storage Sync (Local Mac Repo <--> Portable Archive)

```bash
# View storage status, capacity, and pending sync deltas across both tiers
python3 src/cli.py tier status

# Initialize Dewey taxonomy on both local Mac and the portable archive tier
python3 src/cli.py tier init

# Push local captures & imports to the portable archive with atomic writes and SHA-256 validation
python3 src/cli.py tier push

# Dry-run push to preview transfer without disk mutation
python3 src/cli.py tier push --dry-run

# Conserve Mac SSD space: offload verified files >= 25MB to lightweight stubs
python3 src/cli.py tier push --offload --threshold-mb 25

# Rehydrate an offloaded stub back to full content from the portable archive
python3 src/cli.py tier hydrate ~/KnowRepo_Local/04_Science_and_Reference/heavy_manual.txt.stub.json

# Pull specific categories or master catalog from the portable archive to local Mac
python3 src/cli.py tier pull --categories "01,05"

# Cryptographically verify file integrity against MANIFEST.sha256 across both tiers
python3 src/cli.py tier verify
```

### 2. macOS Native Storage & Volume Management (`kgs mac`)

```bash
# Discover all Mac disks, APFS containers, partitions, and identify portable archive drives
python3 src/cli.py mac list

# Inspect detailed diskutil metadata for any volume/partition
python3 src/cli.py mac info disk5s1

# Safely mount volume (read-only mode supported)
python3 src/cli.py mac mount disk5s1 --readonly

# Flush write buffers and safely unmount volume
python3 src/cli.py mac unmount disk5s1

# Flush write caches and eject the entire external enclosure
python3 src/cli.py mac eject disk4

# Strip .DS_Store and ._* metadata artifacts for clean cross-device portability
python3 src/cli.py mac clean ~/KnowRepo_Local
```

### 3. Web Source Ingestion
Downloads, converts to clean `.md`/`.txt` or saves native `.pdf`/`.epub`, computes checksums, moves to category, and cleans staging:
```bash
# Ingest an article or guide into Category 01 (Medical) as Markdown
python3 src/cli.py ingest "https://example.com/field-first-aid" -c 01 -f md -t "Field First Aid Guide"

# Download a technical manual into Category 03 (Engineering) as PDF
python3 src/cli.py ingest "https://example.com/solar-inverter-wiring.pdf" -c 03 -f pdf

# Auto-detect format and save to Category 05 (Computing)
python3 src/cli.py ingest "https://example.com/linux-networking" -c 05
```

### 4. Clipboard Aggregator
```bash
# Capture current clipboard selection (macOS pbpaste native support)
python3 src/cli.py clip

# Capture with tags and citation notes
python3 src/cli.py clip --tag "medicine,surgery" --note "Emergency wound closure technique"

# Run background clipboard watcher daemon
python3 src/cli.py clipboard-watch --interval 1.0
```

### 5. SD Port & Removable Media Ingest
```bash
# List all connected SD cards / flash media (macOS native diskutil & Linux lsblk)
python3 src/cli.py sd list

# Safely mount read-only, hash-deduplicate, and copy into vault
python3 src/cli.py sd import --device auto

# Safely unmount and eject SD card
python3 src/cli.py sd eject /dev/disk5s1
```

### 6. Integrity, Indexing & Search
```bash
# Rebuild master INDEX.md, index.html, and MANIFEST.sha256
python3 src/cli.py index

# Verify bit-rot and file integrity on attached drive
python3 src/cli.py verify

# View overall repository status
python3 src/cli.py status

# Search across all ingested items and tags in SQLite DB and catalog
python3 src/cli.py search "first aid"
```

---

## Documentation & Manuals

- **[Mac Devices & Portable Archive Drive Integration Guide](docs/MAC_AND_PORTABLE_1TB_DRIVE_INTEGRATION_GUIDE.md)**: Architecture, APFS partition workflows, dual-tier synchronization, storage discovery, and portable archive setup across multiple capacities.
- **[KnowRepo1 Complete Source Duplication & Replication Reference Manual](docs/KNOREPO1_DUPLICATION_AND_REPLICATION_REFERENCE_MANUAL.md)**: Hardware provisioning, replication procedures, and client/host deployment guidance.
- **[SD Card Provisioning & Removable Storage Guide](docs/SD_CARD_PROVISIONING_AND_STORAGE_GUIDE.md)**: Partition layouts and multi-OS deployment.

### Media Duplication Utility (`duplicate_repo.py`)
To clone the complete repository from the primary drive to a secondary SD card or backup vault with 16MB buffered transfers and post-copy verification:
```bash
# Duplicate source to destination
python3 duplicate_repo.py --src /Volumes/990_PRO/KnowRepo_Main_Archive --dst /Volumes/KnowRepo2 --buffer-mb 16

# Verification pass only
python3 duplicate_repo.py --verify-only --src ~/KnowRepo_Local --dst /Volumes/990_PRO/KnowRepo_Main_Archive
```
