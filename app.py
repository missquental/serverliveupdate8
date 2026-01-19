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
import pandas as pd
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
    from googleapiclient.http import MediaFileUpload
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-auth", "google-auth-oauthlib", "google-api-python-client"])
    import google.auth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.http import MediaFileUpload

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

# ... (semua fungsi lainnya tetap sama seperti sebelumnya)

def main():
    # Page configuration must be the first Streamlit command
    st.set_page_config(
        page_title="Advanced YouTube Live Streaming",
        page_icon="📺",
        layout="wide"
    )
    
    # Initialize database
    init_database()
    
    # Initialize session state
    if 'session_id' not in st.session_state:
        st.session_state['session_id'] = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    if 'live_logs' not in st.session_state:
        st.session_state['live_logs'] = []
    
    st.title("🎥 Advanced YouTube Live Streaming Platform")
    st.markdown("---")
    
    # Auto-process authorization code if present
    auto_process_auth_code()
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("📋 Configuration")
        
        # Session info
        st.info(f"🆔 Session: {st.session_state['session_id']}")
        
        # Saved Channels Section
        st.subheader("💾 Saved Channels")
        saved_channels = load_saved_channels()
        
        if saved_channels:
            st.write("**Previously authenticated channels:**")
            for channel in saved_channels:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"📺 {channel['name']}")
                    st.caption(f"Last used: {channel['last_used'][:10]}")
                
                with col2:
                    if st.button("🔑 Use", key=f"use_{channel['name']}"):
                        # Load this channel's authentication
                        service = create_youtube_service(channel['auth'])
                        if service:
                            # Verify the authentication is still valid
                            channels = get_channel_info(service)
                            if channels:
                                channel_info = channels[0]
                                st.session_state['youtube_service'] = service
                                st.session_state['channel_info'] = channel_info
                                update_channel_last_used(channel['name'])
                                st.success(f"✅ Loaded: {channel['name']}")
                                st.rerun()
                            else:
                                st.error("❌ Authentication expired")
                        else:
                            st.error("❌ Failed to load authentication")
        else:
            st.info("No saved channels. Authenticate below to save.")
        
        # Google OAuth Configuration
        st.subheader("🔐 Google OAuth Setup")
        
        # Predefined Auth Button
        st.markdown("### 🚀 Quick Auth (Predefined)")
        if st.button("🔑 Use Predefined OAuth Config", help="Use built-in OAuth configuration"):
            st.session_state['oauth_config'] = PREDEFINED_OAUTH_CONFIG['web']
            st.success("✅ Predefined OAuth config loaded!")
            st.rerun()
        
        # Authorization Process
        if 'oauth_config' in st.session_state:
            oauth_config = st.session_state['oauth_config']
            
            # Generate authorization URL
            auth_url = generate_auth_url(oauth_config)
            if auth_url:
                st.markdown("### 🔗 Authorization Link")
                st.markdown(f"[Click here to authorize]({auth_url})")
                
                # Instructions
                with st.expander("💡 Instructions"):
                    st.write("1. Click the authorization link above")
                    st.write("2. Grant permissions to your YouTube account")
                    st.write("3. You'll be redirected back automatically")
                    st.write("4. Or copy the code from the URL and paste below")
                
                # Manual authorization code input (fallback)
                st.markdown("### 🔑 Manual Code Input")
                auth_code = st.text_input("Authorization Code", type="password", 
                                        placeholder="Paste authorization code here...")
                
                if st.button("🔄 Exchange Code for Tokens"):
                    if auth_code:
                        with st.spinner("Exchanging code for tokens..."):
                            tokens = exchange_code_for_tokens(oauth_config, auth_code)
                            if tokens:
                                st.success("✅ Tokens obtained successfully!")
                                st.session_state['youtube_tokens'] = tokens
                                
                                # Create credentials for YouTube service
                                creds_dict = {
                                    'access_token': tokens['access_token'],
                                    'refresh_token': tokens.get('refresh_token'),
                                    'token_uri': oauth_config['token_uri'],
                                    'client_id': oauth_config['client_id'],
                                    'client_secret': oauth_config['client_secret']
                                }
                                
                                # Test the connection
                                service = create_youtube_service(creds_dict)
                                if service:
                                    channels = get_channel_info(service)
                                    if channels:
                                        channel = channels[0]
                                        st.success(f"🎉 Connected to: {channel['snippet']['title']}")
                                        st.session_state['youtube_service'] = service
                                        st.session_state['channel_info'] = channel
                                        
                                        # Save channel authentication persistently
                                        save_channel_auth(
                                            channel['snippet']['title'],
                                            channel['id'],
                                            creds_dict
                                        )
                                        st.rerun()
                                    else:
                                        st.error("❌ Could not fetch channel information")
                                else:
                                    st.error("❌ Failed to create YouTube service")
                            else:
                                st.error("❌ Failed to exchange code for tokens")
                    else:
                        st.error("Please enter the authorization code")
        
        # Bulk Upload Section
        st.markdown("---")
        st.subheader("📁 Bulk Video Upload")
        if st.button("📤 Manage Bulk Uploads"):
            st.session_state['show_bulk_upload'] = not st.session_state.get('show_bulk_upload', False)
        
        # Log Management
        st.markdown("---")
        st.subheader("📊 Log Management")
        
        col_log1, col_log2 = st.columns(2)
        with col_log1:
            if st.button("🔄 Refresh Logs"):
                st.rerun()
        
        with col_log2:
            if st.button("🗑️ Clear Session Logs"):
                st.session_state['live_logs'] = []
                st.success("Logs cleared!")
        
        # Export logs
        if st.button("📥 Export All Logs"):
            all_logs = get_logs_from_database(limit=1000)
            if all_logs:
                logs_text = "\n".join([f"[{log[0]}] {log[1]}: {log[2]}" for log in all_logs])
                st.download_button(
                    label="💾 Download Logs",
                    data=logs_text,
                    file_name=f"streaming_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain"
                )
    
    # Bulk Upload Interface
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
            
            # Upload multiple video files
            st.subheader("Upload Videos")
            uploaded_files = st.file_uploader("Upload video files", type=['mp4', 'avi', 'mov', 'mkv', 'flv'], accept_multiple_files=True)
            
            if uploaded_files:
                # Save uploaded files temporarily
                temp_dir = f"temp_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                os.makedirs(temp_dir, exist_ok=True)
                video_files = []
                
                for uploaded_file in uploaded_files:
                    file_path = os.path.join(temp_dir, uploaded_file.name)
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.read())
                    video_files.append(file_path)
                
                st.success(f"Uploaded {len(video_files)} video files")
                
                # Konfigurasi bulk upload
                st.subheader("Upload Configuration")
                
                # CSV template download
                if st.button("📥 Download CSV Template"):
                    csv_template = pd.DataFrame({
                        'filename': [os.path.basename(f) for f in video_files],
                        'title': [f"Video Upload {i+1}" for i in range(len(video_files))],
                        'description': [""] * len(video_files),
                        'tags': [""] * len(video_files),
                        'privacy': ["private"] * len(video_files),
                        'category': ["22"] * len(video_files)  # People & Blogs
                    })
                    csv_buffer = io.StringIO()
                    csv_template.to_csv(csv_buffer, index=False)
                    st.download_button(
                        label="💾 Download Template CSV",
                        data=csv_buffer.getvalue(),
                        file_name="bulk_upload_template.csv",
                        mime="text/csv"
                    )
                
                # Upload CSV configuration
                st.subheader("CSV Configuration (Optional)")
                csv_file = st.file_uploader("Upload CSV configuration file", type=['csv'])
                
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
                
                # Buat dataframe untuk preview
                preview_data = []
                titles = []
                descriptions = []
                tags_list = []
                privacy_statuses = []
                category_ids = []
                
                if csv_file:
                    # Baca konfigurasi dari CSV
                    csv_df = pd.read_csv(csv_file)
                    for i, video_file in enumerate(video_files):
                        filename = os.path.basename(video_file)
                        # Cari konfigurasi dari CSV
                        csv_row = csv_df[csv_df['filename'] == filename]
                        if not csv_row.empty:
                            title = csv_row.iloc[0]['title']
                            description = csv_row.iloc[0]['description']
                            tags = csv_row.iloc[0]['tags'].split(',') if csv_row.iloc[0]['tags'] else []
                            privacy = csv_row.iloc[0]['privacy']
                            category = csv_row.iloc[0]['category']
                        else:
                            title = default_title.replace("{index}", str(i+1))
                            description = default_description
                            tags = [tag.strip() for tag in default_tags.split(",") if tag.strip()]
                            privacy = default_privacy
                            category = default_category_id
                        
                        preview_data.append({
                            "Filename": filename,
                            "Title": title,
                            "Description": description[:50] + "..." if len(description) > 50 else description,
                            "Tags": ", ".join(tags),
                            "Privacy": privacy,
                            "Category": categories.get(category, "Unknown")
                        })
                        
                        titles.append(title)
                        descriptions.append(description)
                        tags_list.append(tags)
                        privacy_statuses.append(privacy)
                        category_ids.append(category)
                else:
                    # Gunakan konfigurasi default
                    for i, video_file in enumerate(video_files):
                        filename = os.path.basename(video_file)
                        title = default_title.replace("{index}", str(i+1))
                        description = default_description
                        tags = [tag.strip() for tag in default_tags.split(",") if tag.strip()]
                        privacy = default_privacy
                        category = default_category_id
                        
                        preview_data.append({
                            "Filename": filename,
                            "Title": title,
                            "Description": description[:50] + "..." if len(description) > 50 else description,
                            "Tags": ", ".join(tags),
                            "Privacy": privacy,
                            "Category": categories.get(category, "Unknown")
                        })
                        
                        titles.append(title)
                        descriptions.append(description)
                        tags_list.append(tags)
                        privacy_statuses.append(privacy)
                        category_ids.append(category)
                
                st.dataframe(pd.DataFrame(preview_data))
                
                # Mulai proses upload
                if st.button("🚀 Start Bulk Upload", type="primary"):
                    job_id = f"bulk_job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    
                    # Simpan job ke database
                    save_bulk_upload_job(job_id, channel_name, len(video_files))
                    
                    # Simpan konfigurasi video individu
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
                        if st.button(f"📋 View Details for {job_id}"):
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
                                st.dataframe(pd.DataFrame(video_df))
                            else:
                                st.info("No video details available.")
            else:
                st.info("No bulk upload jobs found.")
    
    # Main content area (existing streaming functionality)
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # ... (semua konten streaming yang ada tetap sama)
        pass
    
    with col2:
        # ... (semua kontrol streaming yang ada tetap sama)
        pass
    
    # Live Logs Section (tetap sama)
    # ... (kode logs tetap sama)

if __name__ == '__main__':
    main()
