# SD Card Provisioning, Removable Storage & Multi-Device Setup Guide

This guide details the complete hardware configuration, filesystem provisioning, replication workflow, and multi-device deployment strategy for the **Knowledge Gathering System (KGS)** offline knowledge vaults (**KnowRepo1**, **KnowRepo2**, and additional device clones).

---

## 1. Physical Media & Hardware Architecture

### Drive Specifications & Layout
The knowledge repository uses dedicated high-speed removable media formatted for broad cross-platform compatibility and high sequential read/write operations (handling large `.zim` archives, SQLite metadata databases, and thousands of indexed articles):

| Repository Identifier | Physical Media | Primary Label | Typical Mount Point | Role |
| :--- | :--- | :--- | :--- | :--- |
| **`KnowRepo1`** | High-Capacity USB 3.x Flash / SSD Drive | `USB Drive` | `~/KnowRepo1`<br>`/mnt/chromeos/shared/removable/USB Drive` | **Primary Knowledge Master** (active downloads, harvesters, staging sync) |
| **`KnowRepo2`** | High-Speed MicroSD / SD Card (UHS-I / V30) | `SD Card` | `~/KnowRepo2`<br>`/mnt/chromeos/shared/removable/SD Card` | **Secondary Knowledge Clone** (read-only distribution, multi-device backup) |
| **`KnowRepoN`** | Additional USB / SD Media | `KnowRepo<N>` | Removable mount path | **Device-Specific Deployments** (field devices, offline laptops, SBCs) |

---

## 2. Partitioning, Formatting & Filesystem Provisioning

When preparing new SD cards or USB storage drives for use with KGS on Linux, ChromeOS, macOS, or Windows devices, follow these formatting guidelines:

### Supported Filesystems
1. **exFAT (Recommended for Cross-Platform & Capacity > 32 GB)**:
   - Full support for files > 4 GB (critical for large Wikipedia `.zim` archives reaching 10–30+ GB).
   - Native read/write access across Linux, ChromeOS, macOS, Windows, Android, and iOS.
   - Recommended cluster size: `128 KB` or `256 KB` for optimal large file streaming throughput.
2. **ext4 (Linux & Single-Board Computers / Raspberry Pi)**:
   - Best POSIX permission handling and symlink support on Linux hosts.
   - Requires 3rd-party drivers on Windows/macOS.
3. **vfat / FAT32 (Legacy Compatibility)**:
   - Limited to 4 GB single file maximum (cannot store monolithic `.zim` full encyclopedia dumps).

### Provisioning a New SD Card / USB on Linux

#### Step 1: Identify Target Block Device
```bash
lsblk -o NAME,PATH,RM,RO,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT
```
Identify the target disk (e.g., `/dev/sda` or `/dev/mmcblk0`). **Caution:** Double-check the device path to prevent overwriting system drives.

#### Step 2: Partition Device (GPT)
```bash
sudo parted --script /dev/sdX mklabel gpt mkpart primary exfat 2048s 100%
```

#### Step 3: Format with exFAT
```bash
sudo mkfs.exfat -n "KnowRepo2" /dev/sdX1
```

#### Step 4: Verify Filesystem & Create Repository Root Directories
Mount the drive and initialize the baseline KGS directory taxonomy:
```bash
mkdir -p /media/user/KnowRepo2/{00_Index_and_Manifests,01_Medical_and_Health,02_Survival_and_Food,03_Engineering_and_Repair,04_Science_and_Reference,05_Computing_and_Comms,06_History_Law_and_Civics,07_Uncategorized_Inbox/{snippets,media,sd_imports}}
```

---

## 3. ChromeOS (Crostini) Container Passthrough & Symlink Mounting

On ChromeOS Crostini environments, removable media is not exposed directly via standard block devices (`/dev/sd*`) inside the container unless shared via the native host UI:

### Sharing Procedure
1. Insert the SD Card or USB Drive into the Chromebook.
2. Open the ChromeOS **Files** application.
3. In the left sidebar, locate **Removable** media (`USB Drive` or `SD Card`).
4. Right-click the drive $\rightarrow$ select **"Share with Linux"**.
5. Inside the Crostini Linux terminal, the drive is mounted via 9p at:
   - `/mnt/chromeos/removable/<Drive Name>` (or `/mnt/chromeos/shared/removable/<Drive Name>`)

### Establishing Persistent User Symlinks
Create convenient standard paths in the user home directory:
```bash
ln -sfn "/mnt/chromeos/shared/removable/USB Drive" ~/KnowRepo1
ln -sfn "/mnt/chromeos/shared/removable/SD Card" ~/KnowRepo2
```

---

## 4. Repository Structure & Category Taxonomy

Both master and cloned repositories maintain an identical Dewey-inspired categorical hierarchy:

```text
KnowRepo/
├── 00_Index_and_Manifests/
│   ├── INDEX.md             # Master Markdown index with category breakdowns
│   ├── index.html           # Offline interactive catalog (JavaScript-based filtering)
│   ├── MANIFEST.sha256      # Checksums for bit-rot detection and verification
│   ├── catalog.json         # Machine-readable inventory of all assets
│   └── kgs_metadata.db      # SQLite query database with full-text search
├── 01_Medical_and_Health/   # Emergency medicine, first aid, sanitation, clinical guides
├── 02_Survival_and_Food/    # Water purification, agriculture, foraging, food preservation
├── 03_Engineering_and_Repair/ # Mechanical, electrical, solar/off-grid, tools, construction
├── 04_Science_and_Reference/ # Chemistry, physics, mathematics, encyclopedias, maps
├── 05_Computing_and_Comms/  # Linux, networking, radio/SDR, cybersecurity, code docs
├── 06_History_Law_and_Civics/ # History, philosophy, governance, law, transcripts
└── 07_Uncategorized_Inbox/  # Ingestion landing zone for review
    ├── snippets/            # Captured text clips and clipboard notes
    ├── media/               # Screenshots, diagrams, and figures
    └── sd_imports/          # Dumped/synced SD card content
```

### Verified Content Audit Baseline
As verified during repository provisioning, a complete KGS image comprises:
- **Total Files**: 4,598 files
- **Total Data Volume**: ~115.58 GB
- **Manifests & DB**: Complete SQLite index and SHA-256 baseline in `00_Index_and_Manifests/`.

---

## 5. High-Throughput Media Replication (`duplicate_repo.py`)

To provision new SD cards or clone existing repositories onto backup drives, use the included high-throughput duplication tool [`duplicate_repo.py`](file:///home/twan102000/Knowledge%20Gathering%20for%20Local%20Repository/duplicate_repo.py).

### Features
- **16 MB Buffered Sequential I/O**: Maximizes sustained write throughput across SD card controllers and 9p virtualization layers.
- **Resumable Transfer**: Scans destination prior to copy; skips unchanged files with matching size.
- **Real-Time Telemetry**: Live progress percentage, write speed (MB/s), ETA, and elapsed time.
- **Periodic Disk Sync**: Flushes buffers via `os.fdatasync` to avoid kernel buffer bloat on removable media.
- **Comprehensive Post-Transfer Audit**: Verifies every directory and file count/size across all 8 taxonomy categories.

### Command Usage

#### Full Duplication (Default: `~/KnowRepo1` $\rightarrow$ `~/KnowRepo2`):
```bash
python3 duplicate_repo.py
```

#### Custom Source and Destination:
```bash
python3 duplicate_repo.py --src /path/to/source --dst /path/to/destination --buffer-mb 16
```

#### Verification Only (Post-Transfer Audit):
```bash
python3 duplicate_repo.py --verify-only --src ~/KnowRepo1 --dst ~/KnowRepo2
```

---

## 6. Multi-Device Deployment & Client Usage

Once provisioned, an SD card or USB vault can be connected to various target client devices without requiring internet access or software installation:

### Client Scenario A: Standalone Laptop / Desktop (Offline Browser)
1. Insert the provisioned SD card or USB drive.
2. Open the file manager and navigate to `00_Index_and_Manifests/`.
3. Double-click **`index.html`** in any standard modern browser (Chrome, Firefox, Safari, Edge).
4. The client browser provides full offline search, filtering by category, and direct links to open local documents, `.zim` archives, PDFs, and notes.

### Client Scenario B: Kiwix Offline Reader (`.zim` Archives)
For full-text encyclopedic viewing of the archives in `04_Science_and_Reference` and `06_History_Law_and_Civics`:
- **Android**: Install Kiwix from APK / F-Droid, grant storage access to SD card, and select the `.zim` files directly.
- **Windows / macOS / Linux**: Download Kiwix Desktop and open files directly from `KnowRepo/`.
- **iOS**: Import via Files app or Wi-Fi sharing.

### Client Scenario C: Single-Board Computers / Raspberry Pi Field Nodes
To serve the knowledge base across a local emergency Wi-Fi network:
```bash
# Start lightweight local web server for the repository catalog
cd /media/KnowRepo/00_Index_and_Manifests
python3 -m http.server 8080 --bind 0.0.0.0
```
Any phone, tablet, or laptop on the local Wi-Fi hotspot can connect to `http://<device-ip>:8080` to search and download materials.

### Client Scenario D: Linux CLI & KGS Integration
To use the KGS management tools on another Linux machine:
```bash
git clone <repository_url>
cd "Knowledge Gathering for Local Repository"
pip install pyyaml pydantic rich

# Query repository status on attached drive
python3 repo_manager.py --repo /media/user/KnowRepo status

# Search articles and documents
python3 repo_manager.py --repo /media/user/KnowRepo search "emergency"

# Verify SHA-256 data integrity
python3 repo_manager.py --repo /media/user/KnowRepo verify
```

---

## 7. Safe Ejection & Disconnection Protocol

To prevent filesystem corruption, bit errors, or incomplete writes:

1. **Flush Kernel Write Caches**:
   ```bash
   sync
   ```
2. **Audit Open Processes**:
   Ensure no background reader, indexing daemon, or terminal shell is holding files open on the drive:
   ```bash
   lsof /mnt/chromeos/shared/removable/* 2>/dev/null || fuser -m /media/KnowRepo* 2>/dev/null
   ```
3. **OS Eject**:
   - On **ChromeOS**: Click the **Eject** ($\mathbf{\underline{\triangle}}$) button next to the drive in the **Files** app.
   - On **Standard Linux**: `udisksctl unmount -b /dev/sdX1 && udisksctl power-off -b /dev/sdX`
   - On **macOS / Windows**: Use standard taskbar/Finder safe eject before physical removal.
