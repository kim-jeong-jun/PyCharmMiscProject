import os
import getpass

# ── NVMe 경로 ──────────────────────────────────────────────────────────────────
INBOX_DIR      = "/home/jjkim/Photos/inbox"       # 카드 → NVMe 임시 보관
SORTED_DIR     = "/home/jjkim/Photos/sorted"      # NVMe 내 RAW 분류 완료본
JPG_SORTED_DIR = "/home/jjkim/Photos/jpg_sorted"  # NVMe 내 JPG 스테이징

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

# ── RAW 배포 매핑: 키는 sorter가 생성하는 폴더명 (CAMERA_NAME_OVERRIDES 적용 후) ──
#
# 드라이브 구조 (2026-05-24 확정):
#   NIKON_0  (7.3TB) : {Camera}/{Year}/{YYYY-MM-DD}/  + JPG/{Camera}/{Year}/{YYYY-MM-DD}/
#                      전 기종 RAW + JPG 공통 백업
#   NIKON_1  (3.6TB) : {Camera}/{Year}/{YYYY-MM-DD}/  + JPG/{Camera}/{Year}/{YYYY-MM-DD}/
#                      D500 제외 모든 Nikon RAW + 전 기종 JPG
#   NIKON_2  (3.6TB) : {Camera}/{Year}/{YYYY-MM-DD}/
#                      D500 전용 RAW 백업
#   LEICA_0/1 (3.6TB): {Camera}/{Year}/{YYYY-MM-DD}/
#   SSD_0/1  (232GB) : {Camera}/{Year}/{YYYY-MM-DD}/  (Canon, Fujifilm, Panasonic)
#   SSD_2/3  (232GB) : MOV/{Camera}/                  (영상 flat 구조)
#
# CAMERA_PREFIX_MAP 폴백: 명시 없는 기종은 브랜드 prefix로 자동 라우팅
#   NIKON 5ED, NIKON D200, NIKON D300, NIKON D7200 등 → [NIKON_0, NIKON_1]
#   LEICA M (Typ 240) 등                              → [LEICA_0, LEICA_1]
#   Canon EOS 시리즈, Panasonic 시리즈                → [SSD_0, SSD_1]
CAMERA_HDD_MAP: dict[str, list[str]] = {
    # ── Nikon ────────────────────────────────────────────────────────────────
    "NIKON D850":  ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON D4S":   ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON D4":    ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON D7000": ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON D500":  ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_2"],  # D500: NIKON_2
    "NIKON D800":  ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON Z 7":   ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    # ── Leica ────────────────────────────────────────────────────────────────
    "LEICA M10":        ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "LEICA M10-R":      ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "M8 Digital Camera":["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "LEICA X2":         ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    # ── Fujifilm (override로 brand prefix 제거된 모델은 명시적으로 등록) ──────
    "X-T5":   ["/media/jjkim/SSD_0", "/media/jjkim/SSD_1"],
    "GFX-50": ["/media/jjkim/SSD_0", "/media/jjkim/SSD_1"],
}

# 위 목록에 없는 기종을 브랜드 prefix로 폴백
CAMERA_PREFIX_MAP: list[tuple[str, list[str]]] = [
    ("NIKON",     ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"]),
    ("LEICA",     ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"]),
    ("CANON",     ["/media/jjkim/SSD_0",   "/media/jjkim/SSD_1"]),
    ("FUJIFILM",  ["/media/jjkim/SSD_0",   "/media/jjkim/SSD_1"]),
    ("PANASONIC", ["/media/jjkim/SSD_0",   "/media/jjkim/SSD_1"]),
]

# ── JPG 배포 매핑 (RAW와 차이: D500 → NIKON_2 대신 NIKON_1) ─────────────────
CAMERA_JPG_HDD_MAP: dict[str, list[str]] = {
    "NIKON D850":  ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON D4S":   ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON D4":    ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON D7000": ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON D500":  ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],  # RAW와 달리 NIKON_1
    "NIKON D800":  ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "NIKON Z 7":   ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"],
    "LEICA M10":        ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "LEICA M10-R":      ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "M8 Digital Camera":["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "LEICA X2":         ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"],
    "X-T5":   ["/media/jjkim/SSD_0", "/media/jjkim/SSD_1"],
    "GFX-50": ["/media/jjkim/SSD_0", "/media/jjkim/SSD_1"],
}
CAMERA_JPG_PREFIX_MAP: list[tuple[str, list[str]]] = [
    ("NIKON",     ["/media/jjkim/NIKON_0", "/media/jjkim/NIKON_1"]),
    ("LEICA",     ["/media/jjkim/LEICA_0", "/media/jjkim/LEICA_1"]),
    ("CANON",     ["/media/jjkim/SSD_0",   "/media/jjkim/SSD_1"]),
    ("FUJIFILM",  ["/media/jjkim/SSD_0",   "/media/jjkim/SSD_1"]),
    ("PANASONIC", ["/media/jjkim/SSD_0",   "/media/jjkim/SSD_1"]),
]

# NIKON 드라이브에서는 JPG를 JPG/ 하위 폴더에 저장 (기존 드라이브 구조 일치)
JPG_PREFIX_HDDS: frozenset[str] = frozenset({
    "/media/jjkim/NIKON_0",
    "/media/jjkim/NIKON_1",
})

# ── EXIF 정규화 이름 → 드라이브 실제 폴더명 오버라이드 ──────────────────────────
# sorter._normalize_camera() 결과가 기존 드라이브 구조와 다를 때 여기서 맞춤.
# 키: _normalize_camera 출력, 값: 드라이브에 실제로 쓸 폴더명
CAMERA_NAME_OVERRIDES: dict[str, str] = {
    "Leica M8 Digital Camera": "M8 Digital Camera",  # EXIF Make: "Leica Camera AG"
    "FUJIFILM X-Pro1":  "Fujifilm X-Pro1",            # 대소문자 불일치
    "FUJIFILM X-T5":    "X-T5",                       # brand prefix 없는 폴더명
    "FUJIFILM GFX100 II": "GFX-50",                   # 폴더명이 기종과 다름
}

# ── 스케줄 ─────────────────────────────────────────────────────────────────────
DISTRIBUTE_AT = "04:00"  # 매일 새벽 4시에 HDD 배포
CHECK_WEEKDAY = "sunday" # 매주 일요일 새벽 3시에 SMART 검사
CHECK_AT      = "03:00"

# ── 기타 ───────────────────────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = ('.nef', '.dng', '.jpg', '.jpeg', '.cr2', '.cr3', '.arw', '.raf')
JPG_EXTENSIONS       = ('.jpg', '.jpeg')
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
