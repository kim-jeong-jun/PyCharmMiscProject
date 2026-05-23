import os
import getpass

# ── NVMe 경로 ──────────────────────────────────────────────────────────────────
INBOX_DIR  = "/home/jjkim/Photos/inbox"   # 카드 → NVMe 임시 보관
SORTED_DIR = "/home/jjkim/Photos/sorted"  # NVMe 내 분류 완료본

# ── SD/CF 카드 감시 경로 ───────────────────────────────────────────────────────
_user = getpass.getuser()
WATCH_DIRS = [
    f"/media/{_user}",
    f"/run/media/{_user}",
]

# ── 수동 드롭 폴더 (바탕화면) ──────────────────────────────────────────────────
DESKTOP_DROP_DIR = os.path.expanduser("~/Desktop/photo_drop")
MOUNT_SETTLE_DELAY = 3  # 마운트 후 읽기 시작까지 대기 (초)

# ── ntfy ──────────────────────────────────────────────────────────────────────
NTFY_URL   = "https://ntfy.sh"
NTFY_TOPIC = "jjkim-photo-pipeline"

# ── 카메라 기종 → HDD 경로 매핑 ────────────────────────────────────────────────
# 키: sorter.py가 생성하는 폴더명 (Make 정규화 후 EXIF Image Model)
# Nikon은 현재 NIKON_0만 사용. NIKON_1/2 분배 전략은 추후 결정.
CAMERA_HDD_MAP: dict[str, list[str]] = {
    # ── Nikon ────────────────────────────────────────────────────────────────
    "NIKON D850":  ["/media/jjkim/NIKON_0"],
    "NIKON D4S":   ["/media/jjkim/NIKON_0"],
    "NIKON D4":    ["/media/jjkim/NIKON_0"],
    "NIKON D7000": ["/media/jjkim/NIKON_0"],
    "NIKON D500":  ["/media/jjkim/NIKON_0"],
    "NIKON D800":  ["/media/jjkim/NIKON_0"],
    "NIKON Z 7":   ["/media/jjkim/NIKON_0"],   # Z7 EXIF model: "NIKON Z 7"
    # ── Leica ────────────────────────────────────────────────────────────────
    "LEICA M10":   ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "LEICA M10-R": ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "LEICA M8":    ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "LEICA X2":    ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
}

# 위 목록에 없는 기종을 브랜드 prefix로 폴백 (sorter가 항상 "NIKON ..." / "LEICA ..." 형태로 정규화)
CAMERA_PREFIX_MAP: list[tuple[str, list[str]]] = [
    ("NIKON", ["/media/jjkim/NIKON_0"]),
    ("LEICA", ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"]),
]

# ── 스케줄 ─────────────────────────────────────────────────────────────────────
DISTRIBUTE_AT = "04:00"  # 매일 새벽 4시에 HDD 배포
CHECK_WEEKDAY = "sunday" # 매주 일요일 새벽 3시에 무결성 검사
CHECK_AT      = "03:00"
DEEP_CHECK_BUDGET_SECONDS = 30 * 60  # 주간 SHA-256 순환 검사 시간 한도

# ── 기타 ───────────────────────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = ('.nef', '.dng', '.jpg', '.jpeg', '.cr2', '.cr3', '.arw', '.raf')
VIDEO_EXTENSIONS     = ('.mov', '.mp4', '.mts', '.m2ts', '.avi', '.mkv')
MANIFEST_FILENAME    = ".photo_manifest.json"  # 각 HDD 루트에 저장되는 체크섬 DB
ERRORS_DIR           = "/home/jjkim/Photos/inbox_errors"  # EXIF 오류 파일 격리

# ── 영상 파이프라인 ────────────────────────────────────────────────────────────
VIDEO_SORTED_DIR = "/home/jjkim/Photos/video_sorted"   # NVMe 영상 스테이징
VIDEO_SSD_LIST   = ["/media/jjkim/SSD_2", "/media/jjkim/SSD_3"]  # 영상 저장 SSD

# ── 경고 임계값 ────────────────────────────────────────────────────────────────
SORTED_WARN_FREE_GB = 20   # NVMe 여유 공간이 이 GB 미만이면 배포 시 경고

# ── 상태 파일 (스케줄 누락 감지용) ───────────────────────────────────────────
STATE_FILE = "/home/jjkim/Photos/.pipeline_state.json"
