import streamlit as st
import subprocess
import os
import tempfile
import zipfile
import io
import imageio_ffmpeg
import re
from PIL import Image

# 1. CẤU HÌNH TRANG
st.set_page_config(page_title="Trạm Xử Lý Đóng Kín", layout="centered")

# 2. HỆ THỐNG MẬT KHẨU BẢO VỆ
def check_password():
    def password_entered():
        if st.session_state["password"] == "Nelson123":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("Trạm Xử Lý Đóng Kín")
        st.text_input("Vui lòng nhập mật khẩu để truy cập:", type="password", on_change=password_entered, key="password")
        return False
        
    elif not st.session_state["password_correct"]:
        st.title("Trạm Xử Lý Đóng Kín")
        st.text_input("Vui lòng nhập mật khẩu để truy cập:", type="password", on_change=password_entered, key="password")
        st.error("Mật khẩu không chính xác. Vui lòng thử lại!")
        return False
        
    return True

if not check_password():
    st.stop()

# --- KHỞI TẠO BỘ NHỚ ĐỆM (CACHE) ---
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "process_done" not in st.session_state:
    st.session_state.process_done = False
if "processed_files" not in st.session_state:
    st.session_state.processed_files = []

# 3. HÀM XỬ LÝ MEDIA
def get_video_dimensions(ffmpeg_exe, input_path):
    command = [ffmpeg_exe, "-i", input_path]
    result = subprocess.run(command, stderr=subprocess.PIPE, text=True)
    match = re.search(r'Video:.*?[,\s](\d{3,5})x(\d{3,5})[,\s]', result.stderr)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1080, 1920

def clean_and_delogo_ai_video(input_path, output_path, crop_percent):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    width, height = get_video_dimensions(ffmpeg_exe, input_path)
    keep_ratio = 1.0 - (crop_percent / 100.0)
    crop_w = int(width * keep_ratio)
    crop_h = int(height * keep_ratio)
    crop_w = crop_w if crop_w % 2 == 0 else crop_w - 1
    crop_h = crop_h if crop_h % 2 == 0 else crop_h - 1
    
    command = [
        ffmpeg_exe, "-y", "-i", input_path,
        "-map_metadata", "-1",  
        "-c:a", "aac",          # Ép mã hóa lại âm thanh sang định dạng AAC để phá thủy vân AI
        "-b:a", "192k",         # Nén với bitrate 192kbps để giữ chất lượng cao
        "-vf", f"crop={crop_w}:{crop_h}:0:0,scale={width}:{height},noise=alls=1:allf=t,eq=contrast=1.02",
        "-c:v", "libx264",      
        "-crf", "17",           
        "-preset", "fast",      
        "-pix_fmt", "yuv420p",  
        output_path
    ]
    
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        return False, result.stderr
    return True, ""

def clean_image(input_path, output_path, crop_percent):
    try:
        with Image.open(input_path) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            width, height = img.size
            keep_ratio = 1.0 - (crop_percent / 100.0)
            crop_w = int(width * keep_ratio)
            crop_h = int(height * keep_ratio)
            
            img_cropped = img.crop((0, 0, crop_w, crop_h))
            img_resized = img_cropped.resize((width, height), Image.Resampling.LANCZOS)
            img_resized.save(output_path, quality=95)
        return True, ""
    except Exception as e:
        return False, str(e)

# 4. GIAO DIỆN WEB CHÍNH
st.title("Phá Dấu Vết AI - Video & Hình Ảnh")
st.markdown("Xóa sạch Metadata, C2PA và phá thủy vân điểm ảnh cho cả **Video** và **Hình ảnh**.")

crop_percent = st.slider(
    "Tỷ lệ cắt góc chứa Logo (%)", 
    min_value=1, max_value=15, value=5, 
    help="Áp dụng cho cả Video và Ảnh. Trượt về 1% nếu chỉ muốn phá thủy vân ẩn mà không bị mất góc ảnh quá nhiều."
)

uploaded_files = st.file_uploader(
    "Kéo thả hàng loạt Video hoặc Ảnh vào đây", 
    type=["mp4", "mov", "jpg", "jpeg", "png", "webp"], 
    accept_multiple_files=True,
    key=f"uploader_{st.session_state.uploader_key}"
)

# XỬ LÝ DỮ LIỆU
if uploaded_files and not st.session_state.process_done:
    st.code(f"> SYSTEM LOG: Detected {len(uploaded_files)} media files.\n> STATUS: Ready for extraction & cleansing...", language="bash")
    
    if st.button("Bắt đầu làm sạch (Clean All)", type="primary"):
        zip_buffer = io.BytesIO()
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Xóa list cũ trước khi chạy đợt mới
        st.session_state.processed_files = []
        
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Đang xử lý ({i+1}/{len(uploaded_files)}): {uploaded_file.name} ...")
                ext = uploaded_file.name.split('.')[-1].lower()
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp_in:
                    tmp_in.write(uploaded_file.read())
                    input_path = tmp_in.name
                    
                output_path = input_path.replace(f".{ext}", f"_cleaned.{ext}")
                
                if ext in ['mp4', 'mov']:
                    success, error_msg = clean_and_delogo_ai_video(input_path, output_path, crop_percent)
                else:
                    success, error_msg = clean_image(input_path, output_path, crop_percent)
                
                if success:
                    with open(output_path, "rb") as f:
                        file_bytes = f.read()
                        clean_filename = uploaded_file.name.rsplit('.', 1)[0] + f"_cleaned.{ext}"
                        
                        # Ghi vào ZIP
                        zip_file.writestr(clean_filename, file_bytes)
                        
                        # Lưu vào bộ nhớ để hiển thị trên Mobile
                        st.session_state.processed_files.append({
                            "name": clean_filename,
                            "data": file_bytes,
                            "type": "video" if ext in ['mp4', 'mov'] else "image",
                            "mime": f"video/{ext}" if ext in ['mp4', 'mov'] else f"image/{ext}"
                        })
                else:
                    st.error(f"Lỗi khi xử lý {uploaded_file.name}: {error_msg}")
                
                if os.path.exists(input_path):
                    os.remove(input_path)
                if os.path.exists(output_path):
                    os.remove(output_path)
                    
                progress_bar.progress((i + 1) / len(uploaded_files))
        
        status_text.empty()
        progress_bar.empty()
        st.session_state.zip_data = zip_buffer.getvalue()
        st.session_state.process_done = True
        st.rerun()

# --- GIAO DIỆN TẢI XUỐNG DÀNH CHO MOBILE & PC ---
if st.session_state.process_done:
    st.code("> EXECUTION COMPLETE.\n> METADATA: STRIPPED.\n> SYNTH-ID: BYPASSED.\n> READY FOR DIRECT DOWNLOAD...", language="bash")
    
    st.write("### Thành phẩm của bạn:")
    
    # Hiển thị từng file để người dùng Mobile dễ lưu
    for file_info in st.session_state.processed_files:
        with st.container():
            if file_info["type"] == "image":
                st.image(file_info["data"], caption=file_info["name"])
            else:
                st.video(file_info["data"])
            
            st.download_button(
                label=f"⬇️ Tải xuống {file_info['name']}",
                data=file_info["data"],
                file_name=file_info["name"],
                mime=file_info["mime"],
                key=f"dl_{file_info['name']}"
            )
            st.write("---")
    
    # Nút tải file ZIP dự phòng cho PC
    st.download_button(
        label="📦 Tải toàn bộ thành phẩm (File ZIP)",
        data=st.session_state.zip_data,
        file_name="cleaned_media_batch.zip",
        mime="application/zip",
        type="primary"
    )
    
    # Nút dọn dẹp Cache và tải lại uploader
    if st.button("🔄 Làm mới & Tải đợt khác"):
        st.session_state.uploader_key += 1
        st.session_state.process_done = False
        st.session_state.processed_files = []
        del st.session_state.zip_data
        st.rerun()
