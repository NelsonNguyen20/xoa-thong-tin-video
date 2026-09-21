import streamlit as st
import subprocess
import os
import tempfile
import zipfile
import io
import imageio_ffmpeg
import re

def get_video_dimensions(ffmpeg_exe, input_path):
    """Sử dụng trực tiếp ffmpeg để đọc thông số phân giải thay vì ffprobe"""
    command = [ffmpeg_exe, "-i", input_path]
    # ffmpeg xuất thông tin metadata ra stderr
    result = subprocess.run(command, stderr=subprocess.PIPE, text=True)
    
    # Tìm kiếm chuỗi định dạng phân giải (VD: 1080x1920)
    match = re.search(r'Video:.*?[,\s](\d{3,5})x(\d{3,5})[,\s]', result.stderr)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1080, 1920 # Mặc định là video dọc nếu không tìm thấy

def clean_and_delogo_ai_video(input_path, output_path, crop_percent):
    """
    Phá SynthID + Cắt bỏ Logo Hữu Hình linh hoạt theo tỷ lệ
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    # Lấy kích thước gốc chuẩn xác
    width, height = get_video_dimensions(ffmpeg_exe, input_path)

    # Tính toán tỷ lệ giữ lại dựa trên % cắt logo
    keep_ratio = 1.0 - (crop_percent / 100.0)
    crop_w = int(width * keep_ratio)
    crop_h = int(height * keep_ratio)
    
    # Đảm bảo kích thước cắt là số chẵn (Bắt buộc đối với chuẩn màu yuv420p)
    crop_w = crop_w if crop_w % 2 == 0 else crop_w - 1
    crop_h = crop_h if crop_h % 2 == 0 else crop_h - 1
    
    command = [
        ffmpeg_exe, "-y", "-i", input_path,
        "-map_metadata", "-1",  
        "-an",                  
        # Cắt góc dưới bên phải -> Kéo giãn lại bằng kích thước gốc -> Thêm nhiễu và tương phản
        "-vf", f"crop={crop_w}:{crop_h}:0:0,scale={width}:{height},noise=alls=1:allf=t,eq=contrast=1.02",
        "-c:v", "libx264",      
        "-crf", "17",           
        "-preset", "fast",      # Tăng tốc độ render cho xử lý hàng loạt
        "-pix_fmt", "yuv420p",  
        output_path
    ]
    
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        return False, result.stderr
    return True, ""

# Giao diện Web App
st.set_page_config(page_title="AI Video Batch Cleaner & Delogo", layout="centered")
st.title("Phá Dấu Vết AI & Xóa Logo")
st.markdown("Hệ thống tự động nhận diện video ngang/dọc. Xóa siêu dữ liệu, phá thủy vân SynthID và cắt bỏ logo hữu hình.")

# Thêm thanh trượt tùy chỉnh để bạn không bị mất quá nhiều khung hình
crop_percent = st.slider(
    "Tỷ lệ cắt góc chứa Logo (%)", 
    min_value=2, max_value=15, value=8, 
    help="Tùy chỉnh độ lớn của mảng cắt. Nếu logo Gemini nhỏ, bạn chỉ cần kéo về 5-8% để giữ lại tối đa hình ảnh."
)

uploaded_files = st.file_uploader("Kéo thả hàng loạt video vào đây (MP4/MOV)", type=["mp4", "mov"], accept_multiple_files=True)

if uploaded_files:
    st.info(f"Đã tải lên {len(uploaded_files)} video. Sẵn sàng xử lý!")
    
    if st.button("Bắt đầu xử lý (Clean & Delogo)", type="primary"):
        zip_buffer = io.BytesIO()
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Đang xử lý ({i+1}/{len(uploaded_files)}): {uploaded_file.name} ...")
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_in:
                    tmp_in.write(uploaded_file.read())
                    input_path = tmp_in.name
                    
                output_path = input_path.replace(".mp4", "_cleaned.mp4")
                
                # Gọi hàm xử lý với biến % cắt
                success, error_msg = clean_and_delogo_ai_video(input_path, output_path, crop_percent)
                
                if success:
                    with open(output_path, "rb") as f:
                        clean_filename = uploaded_file.name.rsplit('.', 1)[0] + "_cleaned.mp4"
                        zip_file.writestr(clean_filename, f.read())
                else:
                    st.error(f"Lỗi khi xử lý {uploaded_file.name}: {error_msg}")
                
                if os.path.exists(input_path):
                    os.remove(input_path)
                if os.path.exists(output_path):
                    os.remove(output_path)
                    
                progress_bar.progress((i + 1) / len(uploaded_files))
        
        status_text.text("Hoàn tất xử lý toàn bộ video!")
        st.success("Tất cả video đã được làm sạch và cắt logo thành công. Hãy tải file Zip về nhé.")
        
        st.download_button(
            label="Tải toàn bộ Video (File ZIP)",
            data=zip_buffer.getvalue(),
            file_name="cleaned_and_delogo_videos.zip",
            mime="application/zip"
        )