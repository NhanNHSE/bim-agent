import os
import glob
import sys

# Đảm bảo in tiếng Việt không bị lỗi encoding trên Windows Console
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass # Python phiên bản cũ không hỗ trợ reconfigure

def count_json_files(folder_path):
    # Kiểm tra xem thư mục có tồn tại hay không
    if not os.path.exists(folder_path):
        print(f"Thư mục không tồn tại: {folder_path}")
        return 0
    
    # Tìm tất cả các file có đuôi .json trong thư mục chỉ định (không quét thư mục con)
    search_path = os.path.join(folder_path, "*.json")
    json_files = glob.glob(search_path)
    count = len(json_files)
    
    print(f"Thư mục: {folder_path}")
    print(f"Tìm thấy {count} file JSON.")
    
    # Nếu muốn đếm cả trong các thư mục con (recursive), bạn có thể dùng:
    # search_path_recursive = os.path.join(folder_path, "**", "*.json")
    # count_recursive = len(glob.glob(search_path_recursive, recursive=True))
    # print(f"Tổng số file JSON (bao gồm cả thư mục con): {count_recursive}")
    
    return count

if __name__ == "__main__":
    # Đường dẫn thư mục cần đếm
    target_folder = r"D:\Data\NhanNH"
    
    count_json_files(target_folder)
