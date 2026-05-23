"""
Stage 4: HDD SMART 상태 검사 (매주 일요일 새벽 3시)
파일 해시 재계산 없이 smartctl로 하드웨어 이상만 탐지.

사전 설정 (최초 1회):
  echo "jjkim ALL=(ALL) NOPASSWD: /usr/sbin/smartctl" | sudo tee /etc/sudoers.d/smartctl
  sudo chmod 440 /etc/sudoers.d/smartctl
"""
import os
import subprocess

from config import CAMERA_HDD_MAP, CAMERA_PREFIX_MAP, ERRORS_DIR
from notifier import notify

# SMART 위험 속성 ID → 한국어 이름
_WARN_ATTRS: dict[str, str] = {
    "5":   "재할당 섹터",
    "196": "재할당 이벤트",
    "197": "펜딩 섹터",
    "198": "수정불가 섹터",
}


def _device_for_mount(mount_point: str) -> str | None:
    r = subprocess.run(
        ["findmnt", "-n", "-o", "SOURCE", mount_point],
        capture_output=True, text=True, timeout=5,
    )
    device = r.stdout.strip()
    return device if device else None


def _smart_check(device: str) -> list[str]:
    """SMART 이상 항목 반환. 정상이면 빈 리스트."""
    warnings: list[str] = []

    # ── 전반적 자가진단 결과 ────────────────────────────────────────────────────
    r = subprocess.run(
        ["sudo", "-n", "smartctl", "-H", device],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 127:
        return ["smartctl 미설치 (sudo apt install smartmontools)"]
    if "sudo" in r.stderr.lower() and "password" in r.stderr.lower():
        return ["smartctl 권한 없음 — /etc/sudoers.d/smartctl 설정 필요"]
    if "FAILED" in r.stdout:
        warnings.append("SMART 자가진단 실패 (즉시 데이터 백업 권장)")

    # ── 위험 속성 확인 ──────────────────────────────────────────────────────────
    r = subprocess.run(
        ["sudo", "-n", "smartctl", "-A", device],
        capture_output=True, text=True, timeout=30,
    )
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 10 or not parts[0].isdigit():
            continue
        attr_id = parts[0]
        if attr_id not in _WARN_ATTRS:
            continue
        try:
            raw = int(parts[9])
        except ValueError:
            continue
        if raw > 0:
            warnings.append(f"{_WARN_ATTRS[attr_id]} {raw}개")

    return warnings


def _count_errors_dir() -> int:
    if not os.path.isdir(ERRORS_DIR):
        return 0
    return sum(1 for _, _, fs in os.walk(ERRORS_DIR) for _ in fs)


def run_integrity_check():
    """CAMERA_HDD_MAP에 등록된 모든 HDD SMART 검사."""
    all_hdds: set[str] = {hdd for lst in CAMERA_HDD_MAP.values() for hdd in lst}
    all_hdds |= {hdd for _, lst in CAMERA_PREFIX_MAP for hdd in lst}

    if not all_hdds:
        print("[검사] CAMERA_HDD_MAP이 비어있습니다.")
        return

    checked: list[str] = []
    skipped: list[str] = []
    all_warnings: list[str] = []

    for hdd in sorted(all_hdds):
        name = os.path.basename(hdd)
        if not os.path.isdir(hdd):
            skipped.append(name)
            continue

        device = _device_for_mount(hdd)
        if not device:
            all_warnings.append(f"[{name}] 디바이스 경로 확인 실패")
            checked.append(name)
            continue

        parent = device.rstrip("0123456789")  # /dev/sda1 → /dev/sda
        print(f"  SMART 검사: {name} ({parent}) ...", end=" ", flush=True)

        warnings = _smart_check(parent)
        if warnings:
            all_warnings.extend(f"[{name}] {w}" for w in warnings)
            print(f"경고 {len(warnings)}건")
        else:
            print("정상")
        checked.append(name)

    errors_dir_count = _count_errors_dir()
    if errors_dir_count:
        all_warnings.append(f"ERRORS_DIR 미처리 파일 {errors_dir_count}개 ({ERRORS_DIR})")

    checked_str = ", ".join(checked) if checked else "없음"
    skipped_str = f"  미연결: {', '.join(skipped)}" if skipped else ""
    summary = f"검사: {checked_str}{skipped_str}"

    if all_warnings:
        preview = "\n".join(all_warnings[:15])
        if len(all_warnings) > 15:
            preview += f"\n... 외 {len(all_warnings) - 15}건"
        print(f"\n[HDD 경고]\n{preview}")
        notify(
            "🚨 HDD 상태 경고",
            f"{len(all_warnings)}건\n{preview}",
            priority="high",
            tags=["warning"],
        )
    else:
        print(f"\n[검사 완료] {summary}")
        notify("✅ HDD 상태 정상", summary, tags=["white_check_mark"])
