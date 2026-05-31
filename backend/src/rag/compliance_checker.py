"""QCVN/TCVN Compliance Checker for generated building designs.

Checks building specifications against Vietnamese building codes:
- QCVN 06:2022/BXD (PCCC)
- QCVN 04:2021/BXD (Nhà ở)
- TCVN 2737:1995 (Tải trọng)
- TCVN 5574:2018 (Kết cấu BTCT)
"""

from dataclasses import dataclass
from typing import Optional
import structlog

logger = structlog.get_logger()


@dataclass
class Violation:
    rule: str
    issue: str
    severity: str  # "error", "warning", "info"
    suggestion: str
    standard: str = ""


def check_compliance(spec) -> list[dict]:
    """Check building spec against QCVN/TCVN rules.

    Args:
        spec: BuildingSpec instance.

    Returns:
        List of violation dicts with rule, issue, severity, suggestion.
    """
    violations = []

    # === QCVN 06: PCCC ===
    _check_fire_safety(spec, violations)

    # === QCVN 04: General building ===
    _check_building_general(spec, violations)

    # === TCVN 2737: Loads ===
    _check_loads(spec, violations)

    # === TCVN 5574: Structure ===
    _check_structure(spec, violations)

    # === General checks ===
    _check_general(spec, violations)

    logger.info("compliance_checked", total=len(violations),
                errors=sum(1 for v in violations if v["severity"] == "error"),
                warnings=sum(1 for v in violations if v["severity"] == "warning"))

    return violations


def _check_fire_safety(spec, violations):
    """QCVN 06:2022/BXD — Phòng cháy chữa cháy."""

    h = spec.num_storeys * spec.storey_height / 1000  # meters

    # Số cầu thang bộ
    if spec.num_storeys > 3 and spec.num_staircases < 2:
        violations.append({
            "rule": "QCVN 06:2022, Điều 3.4.2",
            "issue": f"Nhà {spec.num_storeys} tầng cần ≥2 cầu thang bộ (hiện có {spec.num_staircases})",
            "severity": "error",
            "suggestion": f"Tăng số cầu thang lên ≥2. Gợi ý: đặt ở 2 đầu tòa nhà",
            "standard": "QCVN 06",
        })

    # Chiều rộng lối thoát nạn
    if spec.doors_per_storey < 2 and spec.num_storeys > 2:
        violations.append({
            "rule": "QCVN 06:2022, Điều 3.4.5",
            "issue": f"Mỗi tầng cần ≥2 lối thoát nạn (hiện có {spec.doors_per_storey} cửa)",
            "severity": "error",
            "suggestion": "Thêm cửa thoát nạn. Khoảng cách giữa 2 lối thoát ≥ 5m",
            "standard": "QCVN 06",
        })

    # Khoảng cách thoát nạn tối đa
    max_escape = spec.footprint_length / 1000  # meters
    if max_escape > 40:
        violations.append({
            "rule": "QCVN 06:2022, Điều 3.4.7",
            "issue": f"Khoảng cách thoát nạn xa nhất {max_escape:.0f}m > 40m (giới hạn)",
            "severity": "warning",
            "suggestion": "Bố trí thêm lối thoát nạn hoặc giảm chiều dài tòa nhà",
            "standard": "QCVN 06",
        })

    # Nhà cao tầng (>28m) → yêu cầu đặc biệt
    if h > 28:
        violations.append({
            "rule": "QCVN 06:2022, Điều 7.1",
            "issue": f"Nhà cao {h:.1f}m (>28m) — phân loại nhà cao tầng, cần hệ thống PCCC đặc biệt",
            "severity": "warning",
            "suggestion": "Cần: hệ thống sprinkler, buồng thang bộ N1/N2, hệ thống báo cháy tự động",
            "standard": "QCVN 06",
        })

    # Fire rating theo nhóm nhà
    building_type = spec.building_type.upper()
    if building_type in ("F1", "F2", "F3") and spec.num_storeys > 5:
        violations.append({
            "rule": "QCVN 06:2022, Bảng 4",
            "issue": f"Nhà nhóm {building_type} trên 5 tầng — yêu cầu bậc chịu lửa I hoặc II",
            "severity": "info",
            "suggestion": "Đảm bảo: cột REI 150, dầm REI 120, sàn REI 90, tường REI 120",
            "standard": "QCVN 06",
        })


def _check_building_general(spec, violations):
    """QCVN 04:2021/BXD — Quy chuẩn nhà ở và công trình."""

    storey_h = spec.storey_height / 1000  # meters

    # Chiều cao tầng tối thiểu
    func = spec.building_function.lower()
    if "ở" in func or "chung cư" in func:
        if storey_h < 2.7:
            violations.append({
                "rule": "QCVN 04:2021, Điều 2.3.1",
                "issue": f"Chiều cao tầng {storey_h:.1f}m < 2.7m (tối thiểu cho nhà ở)",
                "severity": "error",
                "suggestion": "Tăng chiều cao tầng lên ≥2.7m",
                "standard": "QCVN 04",
            })
    else:
        if storey_h < 3.0:
            violations.append({
                "rule": "QCVN 04:2021, Điều 2.3.2",
                "issue": f"Chiều cao tầng {storey_h:.1f}m < 3.0m (tối thiểu cho công trình công cộng)",
                "severity": "warning",
                "suggestion": "Khuyến nghị chiều cao tầng ≥3.3m cho văn phòng",
                "standard": "QCVN 04",
            })

    # Diện tích sàn tối thiểu
    floor_area = (spec.footprint_length / 1000) * (spec.footprint_width / 1000)
    if floor_area < 20:
        violations.append({
            "rule": "QCVN 04:2021",
            "issue": f"Diện tích sàn {floor_area:.0f}m² quá nhỏ",
            "severity": "warning",
            "suggestion": "Xem xét tăng kích thước mặt bằng",
            "standard": "QCVN 04",
        })


def _check_loads(spec, violations):
    """TCVN 2737:1995 — Tải trọng và tác động."""

    floor_area = (spec.footprint_length / 1000) * (spec.footprint_width / 1000)
    slab_t = spec.slab_thickness

    # Độ dày sàn tối thiểu
    min_slab = 100 if floor_area < 50 else 150
    if slab_t < min_slab:
        violations.append({
            "rule": "TCVN 2737:1995",
            "issue": f"Độ dày sàn {slab_t:.0f}mm < {min_slab}mm (tối thiểu)",
            "severity": "warning",
            "suggestion": f"Tăng độ dày sàn lên ≥{min_slab}mm",
            "standard": "TCVN 2737",
        })

    # Nhịp sàn vs độ dày
    max_span = max(spec.column_spacing_x, spec.column_spacing_y) / 1000
    min_thickness = max_span * 1000 / 30  # L/30 rule of thumb
    if slab_t < min_thickness:
        violations.append({
            "rule": "TCVN 5574:2018, Bảng 12",
            "issue": f"Nhịp sàn {max_span:.1f}m, độ dày {slab_t:.0f}mm < {min_thickness:.0f}mm (L/30)",
            "severity": "warning",
            "suggestion": f"Tăng độ dày sàn ≥{min_thickness:.0f}mm hoặc giảm nhịp cột",
            "standard": "TCVN 5574",
        })


def _check_structure(spec, violations):
    """TCVN 5574:2018 — Kết cấu bê tông cốt thép."""

    # Khoảng cách cột tối đa
    max_span_x = spec.column_spacing_x / 1000
    max_span_y = spec.column_spacing_y / 1000

    if max_span_x > 8 or max_span_y > 8:
        violations.append({
            "rule": "TCVN 5574:2018",
            "issue": f"Nhịp cột {max(max_span_x, max_span_y):.1f}m > 8m (khuyến nghị cho BTCT thường)",
            "severity": "warning",
            "suggestion": "Giảm khoảng cách cột hoặc sử dụng BTCT dự ứng lực",
            "standard": "TCVN 5574",
        })

    # Kích thước cột tối thiểu
    col_size = spec.column_size
    if spec.num_storeys > 5 and col_size < 500:
        violations.append({
            "rule": "TCVN 5574:2018",
            "issue": f"Cột {col_size:.0f}x{col_size:.0f}mm có thể không đủ cho nhà {spec.num_storeys} tầng",
            "severity": "warning",
            "suggestion": f"Khuyến nghị cột ≥500x500mm cho nhà >5 tầng",
            "standard": "TCVN 5574",
        })

    if spec.num_storeys > 10 and col_size < 600:
        violations.append({
            "rule": "TCVN 5574:2018",
            "issue": f"Cột {col_size:.0f}mm cho nhà {spec.num_storeys} tầng — cần tính toán kết cấu chi tiết",
            "severity": "error",
            "suggestion": "Cột ≥600x600mm, cần tính toán theo TCVN 5574. Liên hệ kỹ sư kết cấu.",
            "standard": "TCVN 5574",
        })


def _check_general(spec, violations):
    """General design checks."""

    # Tỷ lệ mặt bằng
    ratio = spec.footprint_length / spec.footprint_width if spec.footprint_width > 0 else 999
    if ratio > 5:
        violations.append({
            "rule": "Thiết kế kiến trúc",
            "issue": f"Tỷ lệ mặt bằng {ratio:.1f}:1 quá hẹp (>5:1)",
            "severity": "warning",
            "suggestion": "Mặt bằng nên có tỷ lệ ≤4:1 để đảm bảo kết cấu ổn định",
            "standard": "",
        })

    # Số tầng vs chiều cao
    total_h = spec.num_storeys * spec.storey_height / 1000
    if total_h > 75:
        violations.append({
            "rule": "QCVN 06:2022",
            "issue": f"Chiều cao {total_h:.0f}m > 75m — siêu cao tầng, cần thiết kế đặc biệt",
            "severity": "error",
            "suggestion": "Cần: tầng lánh nạn, hệ thống PCCC riêng từng vùng, thang máy cứu hỏa",
            "standard": "QCVN 06",
        })

    # OK checks
    if spec.num_staircases >= 2 and spec.num_storeys > 3:
        violations.append({
            "rule": "QCVN 06:2022, Điều 3.4.2",
            "issue": f"Số cầu thang bộ: {spec.num_staircases} ≥ 2 ✓",
            "severity": "pass",
            "suggestion": "",
            "standard": "QCVN 06",
        })

    storey_h = spec.storey_height / 1000
    if storey_h >= 3.0:
        violations.append({
            "rule": "QCVN 04:2021",
            "issue": f"Chiều cao tầng: {storey_h:.1f}m ≥ 3.0m ✓",
            "severity": "pass",
            "suggestion": "",
            "standard": "QCVN 04",
        })
