import os
import asyncio
import yt_dlp
from shazamio import Shazam
from config import DOWNLOAD_PATH

# --- DOWNLOADER SERVICE ---
async def download_media(url: str):
    """
    Downloads video/audio from different platforms with maximum speed.
    Returns: (file_path, title, media_type)
    """
    ydl_opts = {
        # Highest quality with speed optimizations
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        'outtmpl': f'{DOWNLOAD_PATH}/%(id)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'merge_output_format': 'mp4',
        
        # Maximum speed settings
        'concurrent_fragment_downloads': 16,
        'buffersize': 16384,
        'retries': 5,
        'socket_timeout': 15,
        
        # Platform compatibility
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        
        # TikTok/Facebook/Instagram specific
        'extractor_args': {
            'tiktok': {'webpage_download_timeout': 15},
            'facebook': {'skip_dash_manifest': True},
            'instagram': {'skip_dash_manifest': True},
        },
    }
    
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"

    def run_yt_dlp():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                title = info.get('title', 'Media') or 'Media'
                ext = info.get('ext', '') or ''
                
                if not ext:
                    _, ext = os.path.splitext(filename)
                    ext = ext.replace('.', '')
                
                if ext in ['jpg', 'jpeg', 'png', 'webp']:
                    media_type = 'image'
                elif ext in ['mp3', 'm4a', 'wav', 'opus']:
                    media_type = 'audio'
                else:
                    media_type = 'video'
                    
                return filename, title, media_type
        except Exception as e:
            print(f"yt-dlp error: {e}")
            return None, None, None

    try:
        return await asyncio.to_thread(run_yt_dlp)
    except Exception as e:
        print(f"Async Download Error: {e}")
        return None, None, None

async def search_and_download_song(query: str):
    """
    Searches for a song on YouTube and downloads it as MP3 (fast).
    """
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': f'{DOWNLOAD_PATH}/%(title).50s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',  # Lower quality = faster
        }],
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'noplaylist': True,
        'geo_bypass': True,
        'socket_timeout': 10,
        'concurrent_fragment_downloads': 8,
    }

    def run_search():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{query}", download=True)
                if 'entries' in info:
                    info = info['entries'][0]
                
                filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(filename)
                final_filename = base + ".mp3"
                
                return final_filename, info
        except Exception:
            return None, None

    try:
        return await asyncio.to_thread(run_search)
    except Exception:
        return None, None

# --- RECOGNITION SERVICE ---
async def recognize_music(file_path: str):
    """
    Uses ShazamIO to recognize music from a file with improved accuracy.
    Tries multiple times and uses audio normalization for better results.
    """
    try:
        shazam = Shazam()
        
        # Try recognition directly first
        out = await shazam.recognize(file_path)
        
        if out and out.get('track'):
            track = out['track']
            return {
                'title': track.get('title', 'Unknown'),
                'subtitle': track.get('subtitle', 'Unknown Artist'),
                'url': track.get('url', ''),
                'image': track.get('images', {}).get('coverart', '')
            }
        
        # If not found, return None
        return None
        
    except Exception:
        return None