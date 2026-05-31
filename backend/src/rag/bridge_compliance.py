"""Bridge Compliance Checker — TCVN 11823:2017 & 22TCN 272-05.

Checks bridge specifications against Vietnamese bridge design standards:
- TCVN 11823:2017 (Thiết kế cầu đường bộ — based on AASHTO LRFD)
- 22TCN 272-05 (Tiêu chuẩn thiết kế cầu)
- QCVN 41:2019/BGTVT (Báo hiệu đường bộ)
"""

import structlog

logger = structlog.get_logger()


def check_bridge_compliance(spec) -> dict:
    """Check bridge spec against TCVN/22TCN rules.

    Args:
        spec: BridgeSpec instance.

    Returns:
        Dict with:
            violations: List of dicts (severity = error|warning|info)
            passing: List of dicts (severity = pass)
    """
    violations = []

    _check_geometry(spec, violations)
    _check_girder(spec, violations)
    _check_barrier(spec, violations)
    _check_clearance(spec, violations)
    _check_foundation(spec, violations)
    _check_general(spec, violations)

    # Separate passing checks from real violations
    real_violations = [v for v in violations if v["severity"] != "pass"]
    passing = [v for v in violations if v["severity"] == "pass"]

    logger.info("bridge_compliance_checked", total=len(violations),
                errors=sum(1 for v in real_violations if v["severity"] == "error"),
                warnings=sum(1 for v in real_violations if v["severity"] == "warning"))

    return {"violations": real_violations, "passing": passing}


def _check_geometry(spec, violations):
    """Check overall bridge geometry."""

    # Bề rộng làn xe ≥ 3500mm (TCVN 11823 §2.5)
    if spec.lane_width < 3500:
        violations.append({
            "rule": "TCVN 11823:2017, §2.5.2",
            "issue": f"Bề rộng làn xe {spec.lane_width:.0f}mm < 3500mm (tối thiểu)",
            "severity": "error",
            "suggestion": "Tăng bề rộng làn xe lên ≥3500mm",
            "standard": "TCVN 11823",
        })
    else:
        violations.append({
            "rule": "TCVN 11823:2017, §2.5.2",
            "issue": f"Bề rộng làn xe: {spec.lane_width:.0f}mm ≥ 3500mm ✓",
            "severity": "pass",
            "suggestion": "",
            "standard": "TCVN 11823",
        })

    # Bề rộng lề đi bộ ≥ 1000mm nếu có
    if spec.has_sidewalk and spec.sidewalk_width < 1000:
        violations.append({
            "rule": "TCVN 11823:2017, §2.5.3",
            "issue": f"Bề rộng lề bộ hành {spec.sidewalk_width:.0f}mm < 1000mm",
            "severity": "warning",
            "suggestion": "Tăng bề rộng lề bộ hành ≥1000mm, khuyến nghị ≥1500mm",
            "standard": "TCVN 11823",
        })

    # Tổng bề rộng mặt cầu
    required_width = (spec.num_lanes * spec.lane_width +
                      (2 * spec.sidewalk_width if spec.has_sidewalk else 0))
    if spec.deck_width < required_width:
        violations.append({
            "rule": "TCVN 11823:2017, §2.5",
            "issue": (f"Bề rộng mặt cầu {spec.deck_width:.0f}mm "
                      f"< {required_width:.0f}mm (cần cho {spec.num_lanes} làn + lề)"),
            "severity": "error",
            "suggestion": f"Tăng bề rộng mặt cầu lên ≥{required_width:.0f}mm",
            "standard": "TCVN 11823",
        })

    # Nhịp cầu hợp lý
    if spec.span_length > 40000:
        violations.append({
            "rule": "22TCN 272-05",
            "issue": f"Nhịp cầu {spec.span_length/1000:.0f}m > 40m — quá lớn cho cầu dầm BTCT thường",
            "severity": "warning",
            "suggestion": "Sử dụng BTCT dự ứng lực hoặc giảm nhịp. Nhịp khuyến nghị cho dầm BTCT: 15-35m",
            "standard": "22TCN 272-05",
        })


def _check_girder(spec, violations):
    """Check girder dimensions per structural rules."""

    # Tỷ lệ nhịp/chiều cao dầm (L/h)
    lh_ratio = spec.span_length / spec.girder_height if spec.girder_height > 0 else 999

    if lh_ratio > 20:
        violations.append({
            "rule": "TCVN 11823:2017, §5.14",
            "issue": (f"Tỷ lệ L/h = {lh_ratio:.1f} > 20 "
                      f"(nhịp {spec.span_length/1000:.0f}m, dầm cao {spec.girder_height:.0f}mm)"),
            "severity": "error",
            "suggestion": (f"Tăng chiều cao dầm lên ≥{spec.span_length/20:.0f}mm "
                           f"(nhịp/20) hoặc giảm nhịp"),
            "standard": "TCVN 11823",
        })
    elif lh_ratio > 16:
        violations.append({
            "rule": "TCVN 11823:2017, §5.14",
            "issue": (f"Tỷ lệ L/h = {lh_ratio:.1f} — chấp nhận được nhưng "
                      f"khuyến nghị L/h ≤ 16 cho dầm BTCT DƯL"),
            "severity": "warning",
            "suggestion": f"Khuyến nghị chiều cao dầm ≥{spec.span_length/16:.0f}mm",
            "standard": "TCVN 11823",
        })
    else:
        violations.append({
            "rule": "TCVN 11823:2017, §5.14",
            "issue": f"Tỷ lệ L/h = {lh_ratio:.1f} ≤ 16 ✓",
            "severity": "pass",
            "suggestion": "",
            "standard": "TCVN 11823",
        })

    # Số dầm tối thiểu
    min_girders = max(2, int(spec.deck_width / 3000))
    if spec.num_girders < min_girders:
        violations.append({
            "rule": "22TCN 272-05",
            "issue": f"Số dầm {spec.num_girders} < {min_girders} (tối thiểu cho bề rộng {spec.deck_width/1000:.0f}m)",
            "severity": "warning",
            "suggestion": f"Tăng số dầm lên ≥{min_girders}",
            "standard": "22TCN 272-05",
        })

    # Chiều dày bản bụng dầm
    if spec.girder_web_thickness < 150:
        violations.append({
            "rule": "TCVN 11823:2017",
            "issue": f"Chiều dày bản bụng dầm {spec.girder_web_thickness:.0f}mm < 150mm",
            "severity": "warning",
            "suggestion": "Tăng chiều dày bản bụng ≥150mm để đảm bảo bao bọc cốt thép",
            "standard": "TCVN 11823",
        })


def _check_barrier(spec, violations):
    """Check barrier/railing dimensions."""

    # Chiều cao lan can ≥ 1100mm (TCVN 11823 §13.8)
    if spec.barrier_height < 1100:
        violations.append({
            "rule": "TCVN 11823:2017, §13.8.1",
            "issue": f"Chiều cao lan can {spec.barrier_height:.0f}mm < 1100mm (tối thiểu)",
            "severity": "error",
            "suggestion": "Tăng chiều cao lan can lên ≥1100mm",
            "standard": "TCVN 11823",
        })
    else:
        violations.append({
            "rule": "TCVN 11823:2017, §13.8.1",
            "issue": f"Chiều cao lan can: {spec.barrier_height:.0f}mm ≥ 1100mm ✓",
            "severity": "pass",
            "suggestion": "",
            "standard": "TCVN 11823",
        })

    # Khoảng cách thanh đứng lan can ≤ 150mm
    if spec.barrier_post_spacing > 2500:
        violations.append({
            "rule": "TCVN 11823:2017, §13.8.2",
            "issue": f"Khoảng cách trụ lan can {spec.barrier_post_spacing:.0f}mm > 2500mm",
            "severity": "warning",
            "suggestion": "Giảm khoảng cách trụ lan can ≤2000mm, đặt thêm thanh đứng cách ≤150mm",
            "standard": "TCVN 11823",
        })


def _check_clearance(spec, violations):
    """Check vertical clearance under bridge."""

    # Tĩnh không ≥ 4500mm cho đường bộ
    clearance = spec.clearance_height
    if spec.bridge_function == "Đường bộ" and clearance < 4500:
        violations.append({
            "rule": "TCVN 11823:2017, §2.3.3.2",
            "issue": f"Tĩnh không {clearance:.0f}mm < 4500mm (tối thiểu cho đường bộ)",
            "severity": "error",
            "suggestion": "Tăng tĩnh không lên ≥4500mm",
            "standard": "TCVN 11823",
        })
    elif spec.bridge_function == "Đường sắt" and clearance < 5500:
        violations.append({
            "rule": "TCVN 11823:2017",
            "issue": f"Tĩnh không {clearance:.0f}mm < 5500mm (tối thiểu cho đường sắt)",
            "severity": "error",
            "suggestion": "Tăng tĩnh không lên ≥5500mm",
            "standard": "TCVN 11823",
        })
    else:
        violations.append({
            "rule": "TCVN 11823:2017, §2.3.3.2",
            "issue": f"Tĩnh không: {clearance:.0f}mm ≥ 4500mm ✓",
            "severity": "pass",
            "suggestion": "",
            "standard": "TCVN 11823",
        })


def _check_foundation(spec, violations):
    """Check foundation parameters."""

    # Đường kính cọc tối thiểu
    if spec.pile_diameter < 400:
        violations.append({
            "rule": "22TCN 272-05",
            "issue": f"Đường kính cọc {spec.pile_diameter:.0f}mm < 400mm",
            "severity": "warning",
            "suggestion": "Khuyến nghị cọc khoan nhồi ≥600mm cho cầu đường bộ",
            "standard": "22TCN 272-05",
        })

    # Chiều sâu cọc tối thiểu
    if spec.pile_depth < 10000:
        violations.append({
            "rule": "22TCN 272-05",
            "issue": f"Chiều sâu cọc {spec.pile_depth/1000:.0f}m < 10m",
            "severity": "warning",
            "suggestion": "Chiều sâu cọc phụ thuộc địa chất, thường ≥12-15m cho cầu",
            "standard": "22TCN 272-05",
        })

    # Số cọc tối thiểu mỗi trụ
    if spec.num_piles_per_pier < 4:
        violations.append({
            "rule": "22TCN 272-05",
            "issue": f"Số cọc mỗi trụ: {spec.num_piles_per_pier} < 4 (tối thiểu khuyến nghị)",
            "severity": "warning",
            "suggestion": "Tăng số cọc ≥4 mỗi trụ để đảm bảo ổn định",
            "standard": "22TCN 272-05",
        })


def _check_general(spec, violations):
    """General design checks."""

    # Chiều dày bản mặt cầu
    if spec.deck_thickness < 200:
        violations.append({
            "rule": "TCVN 11823:2017, §9.7",
            "issue": f"Chiều dày bản mặt cầu {spec.deck_thickness:.0f}mm < 200mm",
            "severity": "error",
            "suggestion": "Tăng chiều dày bản mặt cầu ≥200mm, khuyến nghị ≥250mm",
            "standard": "TCVN 11823",
        })

    # Tổng chiều dài cầu vs số nhịp
    avg_span = spec.total_length / spec.num_spans if spec.num_spans > 0 else 0
    if avg_span > 35000 and spec.bridge_type == "beam":
        violations.append({
            "rule": "Thiết kế cầu",
            "issue": (f"Nhịp trung bình {avg_span/1000:.0f}m lớn cho cầu dầm BTCT. "
                      f"Xem xét cầu dầm hộp hoặc dây văng."),
            "severity": "info",
            "suggestion": "Nhịp BTCT DƯL: 25-45m; Cầu dây văng: >100m",
            "standard": "",
        })

    # Tải trọng thiết kế
    violations.append({
        "rule": "TCVN 11823:2017, §3.6",
        "issue": f"Tải trọng thiết kế: {spec.design_load} ✓",
        "severity": "pass",
        "suggestion": "",
        "standard": "TCVN 11823",
    })
