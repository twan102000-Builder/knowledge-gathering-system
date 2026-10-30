## 5. High-Throughput Media Replication (`duplicate_repo.py`)

To provision new SD cards or clone existing repositories onto backup drives, use the included high-throughput duplication tool [`duplicate_repo.py`](../duplicate_repo.py).

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
