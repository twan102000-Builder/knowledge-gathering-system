# Mac Devices & Cross-Device 1TB Portable Removable Drive Integration Guide

This guide details the architecture, setup, and operational workflows for running the Knowledge Gathering System (KGS) across your Apple macOS devices:
1. **Mac mini Setup**: Main storage is the **Samsung 990 PRO NVMe** (`/Volumes/990_PRO`). Preferred location for the Mac mini on-device local repo is `/Volumes/990_PRO/KnowRepo_Local`.
2. **MacBook Pro Setup**: Uses its **internal NVMe drive** (`~/KnowRepo_Local`) for the on-device local repo.
3. **Other Macs / Devices**: Each device runs its local repository on its respective main drive as applicable.
4. **Portable Removable 1TB Drive (Universal Main Know Repo)**: Contains **only one partition available for KnowRepo**. This single partition holds the canonical master repository, shared across the Mac mini, MacBook Pro, and any other device.

---

## 1. Storage Topology & Architecture

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
                                 |          [UNIVERSAL MAIN KNOW REPO ARCHIVE]                 |
                                 |             (Portable Removable 1TB Drive)                  |
                                 |                                                             |
                                 |   Single Dedicated Partition: 'KnowRepo'                    |
                                 |   • Holds the canonical master repository, manifests,       |
                                 |     Dewey categories (00-07), and metadata database         |
                                 |   • Shared across Mac mini, MacBook Pro, and all devices    |
                                 |   • Other sibling partitions on this 1TB drive (if any)     |
                                 |     are non-KnowRepo and preserved untouched                |
                                 +-------------------------------------------------------------+
```

### Core Architectural Principles

1. **Host-Adaptive Local Storage**:
   - `DeviceProfileManager` inspects the machine hardware:
     * When running on the **Mac mini** (where `990_PRO` is attached as main storage), KGS automatically sets the local repo to `/Volumes/990_PRO/KnowRepo_Local`.
     * When running on the **MacBook Pro** (where internal storage is main storage), KGS automatically sets the local repo to `~/KnowRepo_Local`.
     * This requires zero manual path juggling between machines.
2. **Single Dedicated Partition on Portable 1TB Drive**:
   - There is **only one partition available for KnowRepo on the portable drive**.
   - Even if the 1TB drive has other non-KnowRepo partitions (e.g. general media, TimeMachine, exFAT transfer), KGS targets **only that single partition** as the universal Main Know Repo.
   - Sibling partitions are never touched during synchronization passes and are safely dismounted together during drive ejection (`kgs mac eject-portable`).
3. **Cross-Device Knowledge Synchronization**:
   - Ingest snippets, download guides, and save clips on your Mac mini or MacBook Pro locally.
   - When the portable 1TB drive is connected to either machine, run `kgs tier push` to mirror new local items to the shared Master Archive.
   - Run `kgs tier pull` to download updates made on other machines down to your current device.

---

## 2. Command Suite & Workflows

### 1. View Cross-Device Status (`kgs tier status`)
Inspects host device hardware, identifies main storage, and verifies the connection status of the portable 1TB drive:
```bash
python3 src/cli.py tier status
```
*Live Output on Mac mini:*
```text
================================================================================
         Knowledge Gathering System — Cross-Device Architecture
================================================================================
 [HOST DEVICE ENVIRONMENT]:
   • Device Model  : Mac mini ('Workstation Mac mini')
   • Main Storage  : Samsung 990 PRO NVMe (Main Storage)

 [TIER 1] On-Device Local Knowledge Repo (Host Main Storage):
   • Path          : /Volumes/990_PRO/KnowRepo_Local (Active / Not Initialized)
   • Files / Size  : 0 files (0.0 B)
   • Free Space    : 789.6 GB
   • Archived Stubs: 0 offloaded stub(s)

 [TIER 2] Portable Removable 1TB Drive (Universal Main Know Repo):
   • Drive Status  : [DISCONNECTED / WAITING FOR CONNECTION]
   • Note          : Portable 1TB removable drive is not connected. Local captures buffer safely on this device.
   • Single Vault  : Only one partition on the 1TB drive is targeted for KnowRepo.
   • Active Archive: Not connected

 [SYNC DELTA]:
   • Pending Push  : 0 file(s) (0.0 B) awaiting sync to portable 1TB drive
   • Pending Pull  : 0 file(s) (0.0 B) in archive not on this device
================================================================================
```

### 2. Inspect Connected Disks & Partitions (`kgs mac list`)
Shows all internal and host extension drives, and identifies the portable 1TB drive's single KnowRepo partition when plugged in:
```bash
python3 src/cli.py mac list
```

### 3. Initialize Repositories (`kgs tier init`)
Initializes the Dewey taxonomy structure on your active host's local drive (`/Volumes/990_PRO/KnowRepo_Local` on Mac mini, `~/KnowRepo_Local` on MacBook Pro) and on the portable drive's single partition:
```bash
python3 src/cli.py tier init
```

### 4. Synchronize Between Local Device & Portable 1TB Drive
```bash
# Push newly ingested local items to the portable 1TB drive
python3 src/cli.py tier push

# Push and offload large verified files (>=25MB) to lightweight stubs
python3 src/cli.py tier push --offload --threshold-mb 25

# Pull updates made from other devices down to your current machine
python3 src/cli.py tier pull --categories "01,05"
```

### 5. Safely Eject the Portable Drive (`kgs mac eject-portable`)
Safely flushes write buffers across all partitions on the portable physical drive and unmounts them together before powering down the enclosure:
```bash
python3 src/cli.py mac eject-portable
```
*(Host main storage `990_PRO` on Mac mini remains mounted and completely untouched).*

---

## 3. Configuration Reference (`config/kgs_config.yaml`)

```yaml
# Knowledge Gathering System (KGS) Configuration
vault:
  root_path: "auto" # Resolves to /Volumes/990_PRO/KnowRepo_Local on Mac mini, ~/KnowRepo_Local on MacBook
  index_dir: "00_Index_and_Manifests"
  snippets_dir: "07_Uncategorized_Inbox/snippets"
  media_dir: "07_Uncategorized_Inbox/media"
  daily_dir: "07_Uncategorized_Inbox/daily"
  sd_imports_dir: "07_Uncategorized_Inbox/sd_imports"

tier_architecture:
  enabled: true
  local_repo_path: "auto"
  device_profiles:
    mac_mini:
      main_storage: "/Volumes/990_PRO"
      preferred_local_repo: "/Volumes/990_PRO/KnowRepo_Local"
    macbook_pro:
      main_storage: "Internal"
      preferred_local_repo: "~/KnowRepo_Local"
  main_archive:
    auto_detect_portable_drive: true
    target_capacity_gb: 1000
    single_partition_only: true
    knowrepo_partition_keywords:
      - "KnowRepo"
      - "KnowRepo1"
      - "KnowRepo_Archive"
      - "Know_Repo"
  auto_offload_threshold_mb: 25
  clean_macos_artifacts: true
```
