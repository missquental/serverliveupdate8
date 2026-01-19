import sys
import subprocess
import threading
import time
import os
import json
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import urllib.parse
import requests
import sqlite3
from pathlib import Path
import zipfile
import io

# Install required packages
try:
    import streamlit as st
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlit"])
    import streamlit as st

try:
    import google.auth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-auth", "google-auth-oauthlib", "google-api-python-client"])
    import google.auth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

# Predefined OAuth configuration
PREDEFINED_OAUTH_CONFIG = {
    "web": {
        "client_id": "1086578184958-hin4d45sit9ma5psovppiq543eho41sl.apps.googleusercontent.com",
        "project_id": "anjelikakozme",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "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",
        "redirect_uris": ["https://livenews1x.streamlit.app"]
    }
}

# Initialize database for persistent logs
def init_database():
    """Initialize SQLite database for persistent logs"""
    try:
        db_path = Path("streaming_logs.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streaming_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                log_type TEXT NOT NULL,
                message TEXT NOT NULL,
                video_file TEXT,
                stream_key TEXT,
                channel_name TEXT
            )
        ''')
        
        # Create streaming_sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streaming_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                video_file TEXT,
                stream_title TEXT,
                stream_description TEXT,
                tags TEXT,
                category TEXT,
                privacy_status TEXT,
                made_for_kids BOOLEAN,
                channel_name TEXT,
                status TEXT DEFAULT 'active'
            )
        ''')
        
        # Create saved_channels table for persistent authentication
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT UNIQUE NOT NULL,
                channel_id TEXT NOT NULL,
                auth_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used TEXT NOT NULL
            )
        ''')
        
        # Create bulk_upload_jobs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bulk_upload_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                channel_name TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                completed_at TEXT,
                total_videos INTEGER,
                uploaded_videos INTEGER DEFAULT 0,
                failed_videos INTEGER DEFAULT 0,
                progress_percentage REAL DEFAULT 0.0
            )
        ''')
        
        # Create bulk_upload_videos table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bulk_upload_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                video_filename TEXT NOT NULL,
                title TEXT,
                description TEXT,
                tags TEXT,
                privacy_status TEXT,
                category_id TEXT,
                status TEXT DEFAULT 'pending',
                upload_progress REAL DEFAULT 0.0,
                error_message TEXT,
                uploaded_at TEXT,
                FOREIGN KEY (job_id) REFERENCES bulk_upload_jobs(job_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Database initialization error: {e}")

def save_bulk_upload_job(job_id, channel_name, total_videos):
    """Save bulk upload job to database"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO bulk_upload_jobs 
            (job_id, channel_name, created_at, total_videos)
            VALUES (?, ?, ?, ?)
        ''', (
            job_id,
            channel_name,
            datetime.now().isoformat(),
            total_videos
        ))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error saving bulk upload job: {e}")
        return False

def update_bulk_upload_job(job_id, status=None, uploaded_videos=None, failed_videos=None, completed_at=None):
    """Update bulk upload job status"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if status:
            updates.append("status = ?")
            params.append(status)
        
        if uploaded_videos is not None:
            updates.append("uploaded_videos = ?")
            params.append(uploaded_videos)
            
        if failed_videos is not None:
            updates.append("failed_videos = ?")
            params.append(failed_videos)
            
        if completed_at:
            updates.append("completed_at = ?")
            params.append(completed_at)
        
        if updates:
            updates.append("progress_percentage = CAST(uploaded_videos AS REAL) / total_videos * 100")
            query = f'''
                UPDATE bulk_upload_jobs 
                SET {", ".join(updates)}
                WHERE job_id = ?
            '''
            params.append(job_id)
            
            cursor.execute(query, params)
            conn.commit()
        
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating bulk upload job: {e}")
        return False

def save_bulk_upload_video(job_id, video_filename, title, description, tags, privacy_status, category_id):
    """Save individual video for bulk upload"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO bulk_upload_videos 
            (job_id, video_filename, title, description, tags, privacy_status, category_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_id,
            video_filename,
            title,
            description,
            ",".join(tags) if tags else "",
            privacy_status,
            category_id
        ))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error saving bulk upload video: {e}")
        return False

def update_bulk_upload_video_status(job_id, video_filename, status, upload_progress=None, error_message=None):
    """Update status of individual video in bulk upload"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        updates = ["status = ?"]
        params = [status]
        
        if upload_progress is not None:
            updates.append("upload_progress = ?")
            params.append(upload_progress)
            
        if error_message:
            updates.append("error_message = ?")
            params.append(error_message)
            
        if status == "completed":
            updates.append("uploaded_at = ?")
            params.append(datetime.now().isoformat())
        
        query = f'''
            UPDATE bulk_upload_videos 
            SET {", ".join(updates)}
            WHERE job_id = ? AND video_filename = ?
        '''
        params.extend([job_id, video_filename])
        
        cursor.execute(query, params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating bulk upload video status: {e}")
        return False

def get_bulk_upload_jobs():
    """Get all bulk upload jobs"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT job_id, channel_name, status, created_at, completed_at, 
                   total_videos, uploaded_videos, failed_videos, progress_percentage
            FROM bulk_upload_jobs 
            ORDER BY created_at DESC
        ''')
        
        jobs = cursor.fetchall()
        conn.close()
        return jobs
    except Exception as e:
        st.error(f"Error getting bulk upload jobs: {e}")
        return []

def get_bulk_upload_videos(job_id):
    """Get all videos for a bulk upload job"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT video_filename, title, description, tags, privacy_status, category_id,
                   status, upload_progress, error_message, uploaded_at
            FROM bulk_upload_videos 
            WHERE job_id = ?
            ORDER BY video_filename
        ''', (job_id,))
        
        videos = cursor.fetchall()
        conn.close()
        return videos
    except Exception as e:
        st.error(f"Error getting bulk upload videos: {e}")
        return []

def upload_video_to_youtube(service, video_file_path, title, description, tags, privacy_status, category_id, progress_callback=None):
    """Upload a single video to YouTube"""
    try:
        # Define video metadata
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': category_id
            },
            'status': {
                'privacyStatus': privacy_status,
                'madeForKids': False,
                'selfDeclaredMadeForKids': False
            }
        }

        # Create media upload object
        media = MediaFileUpload(video_file_path, chunksize=1024*1024, mimetype='video/*', resumable=True)
        
        # Insert video
        request = service.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_callback:
                progress_callback(status.progress() * 100)
        
        return response
    except Exception as e:
        st.error(f"Error uploading video {video_file_path}: {e}")
        return None

def bulk_upload_videos(service, job_id, video_files, titles, descriptions, tags_list, privacy_statuses, category_ids, channel_name):
    """Bulk upload multiple videos to YouTube"""
    try:
        total_videos = len(video_files)
        uploaded_count = 0
        failed_count = 0
        
        # Update job status to running
        update_bulk_upload_job(job_id, status="running")
        
        for i, video_file in enumerate(video_files):
            video_filename = os.path.basename(video_file)
            title = titles[i] if i < len(titles) else f"Video Upload {i+1}"
            description = descriptions[i] if i < len(descriptions) else ""
            tags = tags_list[i] if i < len(tags_list) else []
            privacy_status = privacy_statuses[i] if i < len(privacy_statuses) else "private"
            category_id = category_ids[i] if i < len(category_ids) else "22"  # People & Blogs default
            
            def progress_callback(progress):
                update_bulk_upload_video_status(job_id, video_filename, "uploading", progress)
            
            # Update video status to uploading
            update_bulk_upload_video_status(job_id, video_filename, "uploading")
            
            # Upload video
            result = upload_video_to_youtube(
                service, video_file, title, description, tags, privacy_status, category_id, progress_callback
            )
            
            if result:
                update_bulk_upload_video_status(job_id, video_filename, "completed")
                uploaded_count += 1
            else:
                update_bulk_upload_video_status(job_id, video_filename, "failed", error_message="Upload failed")
                failed_count += 1
            
            # Update overall job progress
            update_bulk_upload_job(job_id, uploaded_videos=uploaded_count, failed_videos=failed_count)
        
        # Mark job as completed
        update_bulk_upload_job(job_id, status="completed", completed_at=datetime.now().isoformat())
        st.success(f"Bulk upload completed! {uploaded_count} videos uploaded, {failed_count} failed.")
        
    except Exception as e:
        st.error(f"Error in bulk upload process: {e}")
        update_bulk_upload_job(job_id, status="failed")

# ... (bagian lain dari kode tetap sama seperti sebelumnya)

def main():
    # ... (inisialisasi dan konfigurasi awal tetap sama)
    
    # Di bagian sidebar, tambahkan menu baru untuk Bulk Upload
    with st.sidebar:
        st.header("📋 Configuration")
        # ... (konfigurasi lain tetap sama)
        
        st.subheader("📁 Bulk Video Upload")
        if st.button("📤 Manage Bulk Uploads"):
            st.session_state['show_bulk_upload'] = not st.session_state.get('show_bulk_upload', False)
    
    # Di bagian utama, tambahkan interface untuk bulk upload
    if st.session_state.get('show_bulk_upload', False):
        st.header("📁 Bulk Video Upload Manager")
        
        # Tab untuk upload dan history
        bulk_tab1, bulk_tab2 = st.tabs(["📤 New Bulk Upload", "📊 Upload History"])
        
        with bulk_tab1:
            st.subheader("New Bulk Upload Job")
            
            # Cek autentikasi YouTube
            if 'youtube_service' not in st.session_state:
                st.warning("Please authenticate with YouTube first!")
                return
            
            service = st.session_state['youtube_service']
            channel_info = st.session_state.get('channel_info', {})
            channel_name = channel_info.get('snippet', {}).get('title', 'Unknown Channel')
            
            # Upload file ZIP dengan video
            st.subheader("Upload Videos (ZIP file)")
            uploaded_zip = st.file_uploader("Upload ZIP file containing videos", type=['zip'])
            
            if uploaded_zip:
                # Ekstrak file ZIP
                with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                    video_files = []
                    temp_dir = f"temp_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    os.makedirs(temp_dir, exist_ok=True)
                    
                    for file_info in zip_ref.infolist():
                        if file_info.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.flv')):
                            zip_ref.extract(file_info, temp_dir)
                            video_files.append(os.path.join(temp_dir, file_info.filename))
                
                st.success(f"Extracted {len(video_files)} video files")
                
                # Konfigurasi bulk upload
                st.subheader("Upload Configuration")
                
                # Default settings untuk semua video
                default_title = st.text_input("Default Title Template", "Video Upload {index}")
                default_description = st.text_area("Default Description", "Uploaded via bulk upload tool")
                default_tags = st.text_input("Default Tags (comma-separated)", "bulk,upload,youtube")
                default_privacy = st.selectbox("Default Privacy", ["public", "unlisted", "private"], index=2)
                categories = get_youtube_categories()
                category_names = list(categories.values())
                selected_category_name = st.selectbox("Default Category", category_names, index=category_names.index("People & Blogs"))
                default_category_id = [k for k, v in categories.items() if v == selected_category_name][0]
                
                # Preview video files
                st.subheader("Video Files Preview")
                preview_data = []
                for i, video_file in enumerate(video_files):
                    filename = os.path.basename(video_file)
                    preview_data.append({
                        "Filename": filename,
                        "Title": default_title.replace("{index}", str(i+1)),
                        "Description": default_description,
                        "Tags": default_tags,
                        "Privacy": default_privacy,
                        "Category": selected_category_name
                    })
                
                st.dataframe(preview_data)
                
                # Mulai proses upload
                if st.button("🚀 Start Bulk Upload", type="primary"):
                    job_id = f"bulk_job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    
                    # Simpan job ke database
                    save_bulk_upload_job(job_id, channel_name, len(video_files))
                    
                    # Simpan konfigurasi video individu
                    titles = [default_title.replace("{index}", str(i+1)) for i in range(len(video_files))]
                    descriptions = [default_description] * len(video_files)
                    tags_list = [[tag.strip() for tag in default_tags.split(",") if tag.strip()]] * len(video_files)
                    privacy_statuses = [default_privacy] * len(video_files)
                    category_ids = [default_category_id] * len(video_files)
                    
                    for i, video_file in enumerate(video_files):
                        save_bulk_upload_video(
                            job_id, 
                            os.path.basename(video_file),
                            titles[i],
                            descriptions[i],
                            tags_list[i],
                            privacy_statuses[i],
                            category_ids[i]
                        )
                    
                    # Jalankan upload di background
                    upload_thread = threading.Thread(
                        target=bulk_upload_videos,
                        args=(service, job_id, video_files, titles, descriptions, tags_list, privacy_statuses, category_ids, channel_name),
                        daemon=True
                    )
                    upload_thread.start()
                    
                    st.success("Bulk upload started! Check the progress in the Upload History tab.")
                    st.rerun()
        
        with bulk_tab2:
            st.subheader("Upload History")
            
            # Dapatkan daftar job
            jobs = get_bulk_upload_jobs()
            
            if jobs:
                for job in jobs:
                    job_id, channel_name, status, created_at, completed_at, total_videos, uploaded_videos, failed_videos, progress = job
                    
                    with st.expander(f"Job {job_id} - {channel_name} ({status})"):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.write(f"**Created:** {created_at}")
                            st.write(f"**Status:** {status}")
                        with col2:
                            st.write(f"**Total Videos:** {total_videos}")
                            st.write(f"**Uploaded:** {uploaded_videos}")
                            st.write(f"**Failed:** {failed_videos}")
                        with col3:
                            st.progress(progress / 100)
                            st.write(f"Progress: {progress:.1f}%")
                        
                        if completed_at:
                            st.write(f"**Completed:** {completed_at}")
                        
                        # Detail video untuk job ini
                        videos = get_bulk_upload_videos(job_id)
                        if videos:
                            video_df = []
                            for video in videos:
                                video_filename, title, description, tags, privacy_status, category_id, video_status, upload_progress, error_message, uploaded_at = video
                                video_df.append({
                                    "Filename": video_filename,
                                    "Title": title,
                                    "Status": video_status,
                                    "Progress": f"{upload_progress:.1f}%" if upload_progress else "N/A",
                                    "Error": error_message or "None"
                                })
                            st.dataframe(video_df)
            else:
                st.info("No bulk upload jobs found.")
    
    # ... (bagian lain dari aplikasi tetap sama)

# ... (fungsi-fungsi lain tetap sama)

if __name__ == '__main__':
    main()
