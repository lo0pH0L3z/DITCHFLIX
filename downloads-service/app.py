import os
import requests
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)

JACKETT_URL = os.getenv('JACKETT_URL', 'http://jackett:9117')
JACKETT_API_KEY = os.getenv('JACKETT_API_KEY')
QBIT_URL = os.getenv('QBIT_URL', 'http://qbittorrent:8080')
QBIT_USER = os.getenv('QBIT_USER', 'ditchflix')
QBIT_PASS = os.getenv('QBIT_PASS', 'ditchflix')

# Global session for qBittorrent
qbit_session = requests.Session()
last_login_time = 0
LOGIN_COOLDOWN = 60  # Don't try to login more than once per minute if failing

def get_qbit_session():
    global last_login_time
    # Check if we have a SID cookie
    if 'SID' in qbit_session.cookies:
        return qbit_session
    
    # If no cookie, try to login
    current_time = time.time()
    if current_time - last_login_time < LOGIN_COOLDOWN:
        print("Skipping login due to cooldown")
        return qbit_session # Return session anyway, might fail but prevents spam

    try:
        print(f"Attempting login to qBittorrent at {QBIT_URL} with user {QBIT_USER}")
        resp = qbit_session.post(f"{QBIT_URL}/api/v2/auth/login", data={'username': QBIT_USER, 'password': QBIT_PASS}, timeout=10)
        resp.raise_for_status()
        if 'SID' not in qbit_session.cookies and resp.text != "Ok.":
             # Some versions return "Ok." even if no cookie set? No, usually sets cookie.
             # If "Ok." is in text, it succeeded.
             pass
        last_login_time = current_time
        print("Login successful")
    except Exception as e:
        print(f"Login failed: {e}")
        last_login_time = current_time # Set cooldown even on failure
    
    return qbit_session

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/')
@app.route('/download')
@app.route('/download/')
def index():
    return send_from_directory('static', 'index.html')

# Serve static files (CSS, JS, etc.)
@app.route('/static/<path:filename>')
@app.route('/download/static/<path:filename>')
def serve_static_files(filename):
    return send_from_directory('static', filename)

@app.route('/<path:filename>')
@app.route('/download/<path:filename>')
def serve_static(filename):
    # Only serve files that exist in static folder
    if filename.endswith(('.css', '.js', '.png', '.jpg', '.ico', '.svg')):
        return send_from_directory('static', filename)
    # Otherwise 404
    return "Not found", 404

@app.route('/search')
@app.route('/download-api/search')
def search():
    query = request.args.get('q')
    category = request.args.get('category', 'all')
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    try:
        # Jackett API search
        url = f"{JACKETT_URL}/api/v2.0/indexers/all/results"
        params = {
            'apikey': JACKETT_API_KEY,
            'Query': query
        }
        
        if category == 'movies':
            params['Category[]'] = 2000
        elif category == 'tv':
            params['Category[]'] = 5000
        elif category == 'software':
            params['Category[]'] = 4000
        elif category == 'games':
            params['Category[]'] = 1000
        elif category == 'audio':
            params['Category[]'] = 3000
        
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for item in data.get('Results', []):
            results.append({
                'Title': item.get('Title'),
                'Size': item.get('Size'),
                'Seeders': item.get('Seeders'),
                'Peers': item.get('Peers'),
                'Link': item.get('Link') or item.get('MagnetUri'),
                'Indexer': item.get('Indexer'),
                'PublishDate': item.get('PublishDate')
            })
            
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download', methods=['POST'])
@app.route('/download-api/download', methods=['POST'])
def download():
    data = request.json
    magnet = data.get('magnet')
    if not magnet:
        return jsonify({"error": "No magnet link provided"}), 400

    session = get_qbit_session()
    try:
        # Add torrent
        add_resp = session.post(f"{QBIT_URL}/api/v2/torrents/add", data={'urls': magnet}, timeout=60)
        if add_resp.status_code == 403:
            # Try re-login once
            session.cookies.clear()
            get_qbit_session()
            add_resp = session.post(f"{QBIT_URL}/api/v2/torrents/add", data={'urls': magnet}, timeout=60)
            
        add_resp.raise_for_status()
        return jsonify({"status": "success", "message": "Torrent added"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/active-downloads')
@app.route('/download-api/active-downloads')
def active_downloads():
    session = get_qbit_session()
    try:
        resp = session.get(f"{QBIT_URL}/api/v2/torrents/info?filter=all", timeout=10)
        
        if resp.status_code == 403:
            # Try re-login once
            session.cookies.clear()
            get_qbit_session()
            resp = session.get(f"{QBIT_URL}/api/v2/torrents/info?filter=all", timeout=10)

        resp.raise_for_status()
        
        torrents = resp.json()
        results = []
        for t in torrents:
            results.append({
                'name': t.get('name'),
                'progress': t.get('progress', 0) * 100, # 0 to 1
                'eta': t.get('eta'), # seconds
                'dlspeed': t.get('dlspeed'), # bytes/s
                'state': t.get('state'),
                'hash': t.get('hash'),
                'save_path': t.get('save_path')
            })
            
        return jsonify(results)
    except Exception as e:
        # Don't return 500 for auth error, return empty list or specific error so frontend doesn't break
        print(f"Error fetching downloads: {e}")
        return jsonify([])

@app.route('/download-api/pause', methods=['POST'])
def pause_torrent():
    data = request.json
    torrent_hash = data.get('hash')
    if not torrent_hash: return jsonify({"error": "No hash provided"}), 400

    session = get_qbit_session()
    try:
        resp = session.post(f"{QBIT_URL}/api/v2/torrents/pause", data={'hashes': torrent_hash}, timeout=10)
        resp.raise_for_status()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download-api/resume', methods=['POST'])
def resume_torrent():
    data = request.json
    torrent_hash = data.get('hash')
    if not torrent_hash: return jsonify({"error": "No hash provided"}), 400

    session = get_qbit_session()
    try:
        resp = session.post(f"{QBIT_URL}/api/v2/torrents/resume", data={'hashes': torrent_hash}, timeout=10)
        resp.raise_for_status()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download-api/delete', methods=['POST'])
def delete_torrent():
    data = request.json
    torrent_hash = data.get('hash')
    delete_files = data.get('deleteFiles', False)
    
    if not torrent_hash: return jsonify({"error": "No hash provided"}), 400

    session = get_qbit_session()
    try:
        resp = session.post(f"{QBIT_URL}/api/v2/torrents/delete", data={'hashes': torrent_hash, 'deleteFiles': str(delete_files).lower()}, timeout=10)
        resp.raise_for_status()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/debug/files/<hash>')
def debug_files(hash):
    session = get_qbit_session()
    try:
        resp = session.get(f"{QBIT_URL}/api/v2/torrents/files?hash={hash}", timeout=10)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------------------------------------------------------------------------
# Auto-Sorter Logic
# ------------------------------------------------------------------------------
import threading
import shutil
import re
import time

class AutoSorter:
    def __init__(self):
        self.drives = [
            {'path': '/media/A', 'name': 'A-Drive', 'label': 'A'},
            {'path': '/media/B', 'name': 'B-Drive', 'label': 'B'},
            {'path': '/media/E', 'name': 'E-Drive', 'label': 'E'}
        ]
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def get_best_drive(self):
        best_drive = None
        max_free = -1
        
        for drive in self.drives:
            try:
                # Check disk usage
                if not os.path.exists(drive['path']):
                    continue
                total, used, free = shutil.disk_usage(drive['path'])
                if free > max_free:
                    max_free = free
                    best_drive = drive
            except Exception as e:
                print(f"Error checking drive {drive['path']}: {e}")
        
        return best_drive

    def categorize(self, name):
        # Simple regex to guess if it's a show
        # Looks for S01E01, S01, Season 1, etc.
        if re.search(r'(s\d{1,2}e\d{1,2}|season\s?\d+|complete\s?series|collection)', name, re.IGNORECASE):
            return 'Shows'
        return 'Movies'

    def run(self):
        print("AutoSorter started...")
        while self.running:
            try:
                session = get_qbit_session()
                # Get all completed torrents
                resp = session.get(f"{QBIT_URL}/api/v2/torrents/info?filter=completed", timeout=30)
                if resp.status_code != 200:
                    time.sleep(60)
                    continue
                
                torrents = resp.json()
                for t in torrents:
                    save_path = t.get('save_path', '')
                    # Only move if it's in the default download location (or not already in a media drive)
                    if '/downloads' in save_path or save_path == '/downloads':
                        name = t.get('name')
                        category = self.categorize(name)
                        best_drive = self.get_best_drive()
                        
                        if best_drive:
                            # Construct new path: /media/A/A-Movies or /media/A/A-Shows
                            # Note: User's folder structure seems to be X-Movies/X-Shows
                            target_folder = f"{best_drive['label']}-{category}" # e.g. A-Movies
                            new_path = os.path.join(best_drive['path'], target_folder)
                            
                            print(f"Moving '{name}' to {new_path} (Free space: {format_bytes(shutil.disk_usage(best_drive['path'])[2])})")
                            
                            # Call qBit to move
                            move_resp = session.post(f"{QBIT_URL}/api/v2/torrents/setLocation", data={'hashes': t.get('hash'), 'location': new_path}, timeout=30)
                            if move_resp.status_code == 200:
                                print(f"Successfully moved '{name}'")
                            else:
                                print(f"Failed to move '{name}': {move_resp.text}")
                        else:
                            print("No suitable drive found!")
                            
            except Exception as e:
                print(f"AutoSorter Error: {e}")
            
            time.sleep(60) # Check every minute

def format_bytes(size):
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"

# Start AutoSorter globally so Gunicorn picks it up
try:
    sorter = AutoSorter()
except Exception as e:
    print(f"Failed to start AutoSorter: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8001)
