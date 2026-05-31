"""Sample QCVN/TCVN data generator.

Tạo dữ liệu mẫu có cấu trúc từ các QCVN/TCVN xây dựng phổ biến.
Dữ liệu này dùng để xây dựng và test pipeline trước khi có PDF thật.
"""

import json
import os

SAMPLE_DATA = [
    {
        "standard_code": "QCVN 06:2022/BXD",
        "standard_name": "Quy chuẩn kỹ thuật quốc gia về An toàn cháy cho nhà và công trình",
        "year": 2022,
        "issuing_body": "Bộ Xây dựng",
        "status": "active",
        "scope": "Áp dụng cho thiết kế mới, cải tạo nhà và công trình trên lãnh thổ Việt Nam",
        "supersedes": "QCVN 06:2021/BXD",
        "related_standards": ["TCVN 2622:1995", "TCVN 3890:2023", "TCVN 5738:2021"],
        "chapters": [
            {
                "number": 1,
                "title": "Quy định chung",
                "sections": [
                    {
                        "number": "1.1",
                        "title": "Phạm vi điều chỉnh",
                        "articles": [
                            {
                                "number": "1.1.1",
                                "title": "Phạm vi áp dụng",
                                "content": "Quy chuẩn này quy định các yêu cầu chung về an toàn cháy cho nhà và công trình xây dựng mới, cải tạo, thay đổi công năng sử dụng. Áp dụng cho tất cả các loại nhà và công trình trên lãnh thổ Việt Nam, trừ nhà ở riêng lẻ có chiều cao không quá 6 tầng.",
                                "requirements": []
                            },
                            {
                                "number": "1.1.2",
                                "title": "Phân loại nguy hiểm cháy",
                                "content": "Nhà và công trình được phân loại theo mức độ nguy hiểm cháy dựa trên công năng sử dụng, bao gồm các nhóm: F1 (nhà ở, khách sạn), F2 (nhà văn hóa, giải trí), F3 (cơ sở dịch vụ), F4 (cơ sở giáo dục, khoa học), F5 (nhà sản xuất, kho).",
                                "requirements": [
                                    {
                                        "type": "classification",
                                        "description": "Phân loại nhà theo nhóm nguy hiểm cháy",
                                        "values": {
                                            "F1": "Nhà ở, ký túc xá, khách sạn, bệnh viện",
                                            "F2": "Rạp chiếu phim, nhà hát, bảo tàng, thư viện",
                                            "F3": "Cửa hàng, trung tâm thương mại, nhà hàng",
                                            "F4": "Trường học, viện nghiên cứu, cơ quan hành chính",
                                            "F5": "Nhà máy sản xuất, nhà kho, bãi đỗ xe"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "number": 2,
                "title": "Bậc chịu lửa của nhà và công trình",
                "sections": [
                    {
                        "number": "2.1",
                        "title": "Phân loại bậc chịu lửa",
                        "articles": [
                            {
                                "number": "2.1.1",
                                "title": "Các bậc chịu lửa",
                                "content": "Nhà và công trình được phân thành 5 bậc chịu lửa (I, II, III, IV, V) dựa trên giới hạn chịu lửa tối thiểu của các kết cấu xây dựng chính.",
                                "requirements": [
                                    {
                                        "type": "fire_resistance",
                                        "description": "Giới hạn chịu lửa tối thiểu của cột chịu lực",
                                        "building_element": "Cột chịu lực",
                                        "values": {
                                            "Bậc I": {"min_value": 150, "unit": "phút"},
                                            "Bậc II": {"min_value": 120, "unit": "phút"},
                                            "Bậc III": {"min_value": 120, "unit": "phút"},
                                            "Bậc IV": {"min_value": 30, "unit": "phút"},
                                            "Bậc V": {"min_value": 0, "unit": "phút", "note": "Không quy định"}
                                        }
                                    },
                                    {
                                        "type": "fire_resistance",
                                        "description": "Giới hạn chịu lửa tối thiểu của sàn",
                                        "building_element": "Sàn",
                                        "values": {
                                            "Bậc I": {"min_value": 60, "unit": "phút"},
                                            "Bậc II": {"min_value": 45, "unit": "phút"},
                                            "Bậc III": {"min_value": 45, "unit": "phút"},
                                            "Bậc IV": {"min_value": 15, "unit": "phút"},
                                            "Bậc V": {"min_value": 0, "unit": "phút"}
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "number": 3,
                "title": "Lối thoát nạn",
                "sections": [
                    {
                        "number": "3.1",
                        "title": "Yêu cầu chung về thoát nạn",
                        "articles": [
                            {
                                "number": "3.1.1",
                                "title": "Số lối thoát nạn tối thiểu",
                                "content": "Mỗi tầng nhà phải có ít nhất 2 lối thoát nạn. Cho phép bố trí 1 lối thoát nạn duy nhất cho tầng nhà khi số người trên tầng đó không quá 20 người và khoảng cách từ vị trí xa nhất đến lối ra thoát nạn không quá 25m.",
                                "requirements": [
                                    {
                                        "type": "minimum_count",
                                        "description": "Số lối thoát nạn tối thiểu mỗi tầng",
                                        "min_value": 2,
                                        "unit": "lối",
                                        "exception": "Cho phép 1 lối khi số người ≤ 20 và khoảng cách ≤ 25m"
                                    }
                                ]
                            },
                            {
                                "number": "3.1.2",
                                "title": "Chiều rộng lối thoát nạn",
                                "content": "Chiều rộng thông thủy tối thiểu của lối ra thoát nạn phải đảm bảo không nhỏ hơn 1,2m đối với hành lang; 0,9m đối với cửa đi; 1,05m đối với cầu thang bộ khi số người thoát nạn lớn hơn 15 người.",
                                "requirements": [
                                    {
                                        "type": "minimum_dimension",
                                        "description": "Chiều rộng tối thiểu hành lang thoát nạn",
                                        "min_value": 1.2,
                                        "unit": "m",
                                        "applies_to": "Hành lang thoát nạn"
                                    },
                                    {
                                        "type": "minimum_dimension",
                                        "description": "Chiều rộng tối thiểu cửa thoát nạn",
                                        "min_value": 0.9,
                                        "unit": "m",
                                        "applies_to": "Cửa đi thoát nạn"
                                    },
                                    {
                                        "type": "minimum_dimension",
                                        "description": "Chiều rộng tối thiểu cầu thang thoát nạn",
                                        "min_value": 1.05,
                                        "unit": "m",
                                        "applies_to": "Cầu thang bộ thoát nạn",
                                        "condition": "Khi số người > 15"
                                    }
                                ]
                            },
                            {
                                "number": "3.1.3",
                                "title": "Khoảng cách tối đa đến lối thoát nạn",
                                "content": "Khoảng cách giới hạn tối đa từ vị trí xa nhất trong phòng đến lối ra thoát nạn gần nhất phụ thuộc vào bậc chịu lửa của nhà, nhóm nguy hiểm cháy và mật độ người sử dụng.",
                                "requirements": [
                                    {
                                        "type": "maximum_distance",
                                        "description": "Khoảng cách tối đa đến lối thoát nạn — nhà nhóm F1",
                                        "applies_to": "F1",
                                        "values": {
                                            "Bậc I, II": {"max_value": 40, "unit": "m"},
                                            "Bậc III": {"max_value": 30, "unit": "m"},
                                            "Bậc IV": {"max_value": 25, "unit": "m"},
                                            "Bậc V": {"max_value": 20, "unit": "m"}
                                        }
                                    },
                                    {
                                        "type": "maximum_distance",
                                        "description": "Khoảng cách tối đa đến lối thoát nạn — nhà nhóm F4",
                                        "applies_to": "F4",
                                        "values": {
                                            "Bậc I, II": {"max_value": 50, "unit": "m"},
                                            "Bậc III": {"max_value": 40, "unit": "m"},
                                            "Bậc IV": {"max_value": 30, "unit": "m"},
                                            "Bậc V": {"max_value": 25, "unit": "m"}
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    {
        "standard_code": "QCVN 03:2022/BXD",
        "standard_name": "Quy chuẩn kỹ thuật quốc gia về Phân cấp công trình phục vụ thiết kế xây dựng",
        "year": 2022,
        "issuing_body": "Bộ Xây dựng",
        "status": "active",
        "scope": "Phân cấp công trình xây dựng theo quy mô, tầm quan trọng để xác định yêu cầu thiết kế",
        "supersedes": "QCVN 03:2012/BXD",
        "related_standards": ["TCVN 2737:2023", "QCVN 06:2022/BXD"],
        "chapters": [
            {
                "number": 1,
                "title": "Quy định chung",
                "sections": [
                    {
                        "number": "1.1",
                        "title": "Phạm vi và đối tượng áp dụng",
                        "articles": [
                            {
                                "number": "1.1.1",
                                "title": "Phạm vi điều chỉnh",
                                "content": "Quy chuẩn này quy định về phân cấp công trình xây dựng dân dụng, công nghiệp và hạ tầng kỹ thuật theo quy mô, mức độ quan trọng nhằm xác định các yêu cầu kỹ thuật trong thiết kế, thi công, nghiệm thu và bảo trì.",
                                "requirements": []
                            }
                        ]
                    }
                ]
            },
            {
                "number": 2,
                "title": "Phân cấp công trình",
                "sections": [
                    {
                        "number": "2.1",
                        "title": "Cấp công trình dân dụng",
                        "articles": [
                            {
                                "number": "2.1.1",
                                "title": "Phân cấp nhà ở và nhà công cộng",
                                "content": "Nhà ở và công trình công cộng được phân thành 5 cấp (Đặc biệt, I, II, III, IV) dựa trên quy mô, chiều cao, tổng diện tích sàn và tầm quan trọng.",
                                "requirements": [
                                    {
                                        "type": "classification",
                                        "description": "Phân cấp nhà ở theo chiều cao",
                                        "values": {
                                            "Cấp đặc biệt": "Chiều cao > 200m hoặc nhịp > 100m",
                                            "Cấp I": "Chiều cao > 75m hoặc tổng diện tích sàn > 10.000m²",
                                            "Cấp II": "Chiều cao > 28m hoặc tổng diện tích sàn > 5.000m²",
                                            "Cấp III": "Chiều cao > 15m hoặc tổng diện tích sàn > 1.000m²",
                                            "Cấp IV": "Chiều cao ≤ 15m và tổng diện tích sàn ≤ 1.000m²"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    {
        "standard_code": "TCVN 2737:2023",
        "standard_name": "Tải trọng và tác động — Tiêu chuẩn thiết kế",
        "year": 2023,
        "issuing_body": "Bộ Khoa học và Công nghệ",
        "status": "active",
        "scope": "Quy định tải trọng và tác động dùng trong thiết kế kết cấu nhà và công trình xây dựng",
        "supersedes": "TCVN 2737:1995",
        "related_standards": ["TCVN 5574:2018", "QCVN 02:2022/BXD"],
        "chapters": [
            {
                "number": 1,
                "title": "Phạm vi áp dụng",
                "sections": [
                    {
                        "number": "1.1",
                        "title": "Quy định chung",
                        "articles": [
                            {
                                "number": "1.1.1",
                                "title": "Phạm vi",
                                "content": "Tiêu chuẩn này quy định tải trọng và tác động, giá trị tiêu chuẩn, hệ số tin cậy về tải trọng dùng khi thiết kế kết cấu và nền móng nhà và công trình xây dựng.",
                                "requirements": []
                            }
                        ]
                    }
                ]
            },
            {
                "number": 3,
                "title": "Tải trọng thường xuyên",
                "sections": [
                    {
                        "number": "3.1",
                        "title": "Trọng lượng bản thân kết cấu",
                        "articles": [
                            {
                                "number": "3.1.1",
                                "title": "Trọng lượng riêng vật liệu",
                                "content": "Trọng lượng riêng tiêu chuẩn của các vật liệu xây dựng thông dụng dùng để tính toán tải trọng thường xuyên.",
                                "requirements": [
                                    {
                                        "type": "material_property",
                                        "description": "Trọng lượng riêng tiêu chuẩn",
                                        "values": {
                                            "Bê tông cốt thép": {"value": 25, "unit": "kN/m³"},
                                            "Bê tông thường": {"value": 24, "unit": "kN/m³"},
                                            "Thép": {"value": 78.5, "unit": "kN/m³"},
                                            "Gạch đặc": {"value": 18, "unit": "kN/m³"},
                                            "Gạch rỗng": {"value": 14, "unit": "kN/m³"},
                                            "Gỗ nhóm II-IV": {"value": 7, "unit": "kN/m³"},
                                            "Kính": {"value": 25, "unit": "kN/m³"}
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "number": 4,
                "title": "Tải trọng tạm thời",
                "sections": [
                    {
                        "number": "4.1",
                        "title": "Hoạt tải sàn",
                        "articles": [
                            {
                                "number": "4.1.1",
                                "title": "Hoạt tải tiêu chuẩn trên sàn",
                                "content": "Hoạt tải tiêu chuẩn trên sàn phụ thuộc vào công năng sử dụng của phòng. Giá trị hoạt tải bao gồm thành phần dài hạn và thành phần ngắn hạn.",
                                "requirements": [
                                    {
                                        "type": "live_load",
                                        "description": "Hoạt tải tiêu chuẩn trên sàn theo công năng",
                                        "values": {
                                            "Phòng ở, phòng ngủ": {"value": 1.5, "unit": "kN/m²", "long_term": 0.35},
                                            "Văn phòng": {"value": 2.0, "unit": "kN/m²", "long_term": 0.7},
                                            "Phòng họp, hội trường": {"value": 4.0, "unit": "kN/m²", "long_term": 1.4},
                                            "Sàn cửa hàng, siêu thị": {"value": 4.0, "unit": "kN/m²", "long_term": 1.4},
                                            "Phòng đọc thư viện": {"value": 4.0, "unit": "kN/m²", "long_term": 2.0},
                                            "Kho sách thư viện": {"value": 5.0, "unit": "kN/m²", "long_term": 4.0},
                                            "Sảnh, hành lang tầng 1": {"value": 3.0, "unit": "kN/m²", "long_term": 1.0},
                                            "Ban công, lô gia": {"value": 2.0, "unit": "kN/m²", "long_term": 0.7},
                                            "Sân thượng": {"value": 0.75, "unit": "kN/m²", "long_term": 0.35},
                                            "Gara ô tô con": {"value": 5.0, "unit": "kN/m²", "long_term": 1.5}
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
]


def generate_sample_data(output_dir: str = "data/qcvn") -> list[str]:
    """Generate structured QCVN/TCVN sample data as JSON files.

    Args:
        output_dir: Directory to save JSON files.

    Returns:
        List of created file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    created_files = []

    for standard in SAMPLE_DATA:
        code = standard["standard_code"].replace(":", "_").replace("/", "_")
        filepath = os.path.join(output_dir, f"{code}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(standard, f, ensure_ascii=False, indent=2)
        created_files.append(filepath)
        print(f"✅ Created: {filepath}")

    print(f"\n📋 Generated {len(created_files)} sample data files")
    return created_files


if __name__ == "__main__":
    generate_sample_data()
