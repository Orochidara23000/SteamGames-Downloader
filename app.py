import os
import sys
import subprocess
import re
import time
import gradio as gr
import logging
import zipfile
import requests
import threading
import shutil
from pathlib import Path
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("steamcmd_downloader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SteamCMD-Downloader")

# Configuration
STEAMCMD_DIR = os.path.join(os.getcwd(), "steamcmd")
STEAMCMD_EXE = os.path.join(STEAMCMD_DIR, "steamcmd.exe") if sys.platform == "win32" else os.path.join(STEAMCMD_DIR, "steamcmd.sh")
GAMES_DIR = os.path.join(os.getcwd(), "games")
PUBLIC_DIR = os.path.join(os.getcwd(), "public")
STEAMCMD_DOWNLOAD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" if sys.platform == "win32" else "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"

# Ensure directories exist
os.makedirs(STEAMCMD_DIR, exist_ok=True)
os.makedirs(GAMES_DIR, exist_ok=True)
os.makedirs(PUBLIC_DIR, exist_ok=True)

class SteamCMDDownloader:
    def __init__(self):
        self.process = None
        self.current_download = {
            "game_id": None,
            "progress": 0,
            "status": "idle",
            "start_time": None,
            "current_size": 0,
            "total_size": 0,
            "speed": 0,
            "remaining_time": None,
            "log": []
        }
        self.public_links = []
    
    def check_steamcmd_installed(self):
        """Check if SteamCMD is installed and in the expected location"""
        if sys.platform == "win32":
            return os.path.exists(STEAMCMD_EXE)
        else:
            return os.path.exists(STEAMCMD_EXE) and os.access(STEAMCMD_EXE, os.X_OK)
    
    def install_steamcmd(self):
        """Install SteamCMD in the designated directory"""
        try:
            logger.info("Installing SteamCMD...")
            
            # Download SteamCMD
            response = requests.get(STEAMCMD_DOWNLOAD_URL, stream=True)
            response.raise_for_status()
            
            # Save the download
            download_path = os.path.join(STEAMCMD_DIR, "steamcmd_installer")
            if sys.platform == "win32":
                download_path += ".zip"
            else:
                download_path += ".tar.gz"
                
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Extract the download
            if sys.platform == "win32":
                with zipfile.ZipFile(download_path, 'r') as zip_ref:
                    zip_ref.extractall(STEAMCMD_DIR)
            else:
                subprocess.run(["tar", "-xzf", download_path, "-C", STEAMCMD_DIR], check=True)
                subprocess.run(["chmod", "+x", STEAMCMD_EXE], check=True)
            
            # Verify installation
            if not self.check_steamcmd_installed():
                logger.error("Failed to install SteamCMD correctly")
                return False
                
            logger.info("SteamCMD installed successfully")
            # Run SteamCMD once to update itself
            self._run_steamcmd_command("+quit")
            return True
            
        except Exception as e:
            logger.error(f"Failed to install SteamCMD: {str(e)}")
            return False
    
    def _extract_game_id(self, game_input):
        """Extract numeric game ID from input (URL or direct ID)"""
        # If it's already a numeric ID
        if game_input.isdigit():
            return game_input
            
        # Try to extract ID from URL
        match = re.search(r'app/(\d+)', game_input)
        if match:
            return match.group(1)
            
        # If we can't extract an ID, return None
        return None
    
    def _run_steamcmd_command(self, command):
        """Run a SteamCMD command and return the output"""
        full_command = f"{STEAMCMD_EXE} {command}"
        process = subprocess.run(full_command, shell=True, capture_output=True, text=True)
        return process.stdout, process.stderr
    
    def login(self, username, password, anonymous=False):
        """Attempt to login to Steam via SteamCMD"""
        try:
            if anonymous:
                logger.info("Logging in anonymously...")
                cmd = "+login anonymous"
            else:
                logger.info(f"Logging in as {username}...")
                cmd = f"+login {username} {password}"
                
            stdout, stderr = self._run_steamcmd_command(cmd + " +quit")
            
            if "Login Failure" in stdout or "FAILED" in stdout:
                logger.error("Login failed")
                return False, "Login failed. Please check your credentials."
                
            logger.info("Login successful")
            return True, "Login successful"
            
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return False, f"Login error: {str(e)}"
    
    def _parse_progress(self, line):
        """Parse SteamCMD output to extract download progress information"""
        # Update progress percentage
        progress_match = re.search(r'(\d+\.?\d*)%', line)
        if progress_match:
            self.current_download["progress"] = float(progress_match.group(1))
        
        # Update download size information
        size_match = re.search(r'(\d+\.?\d*) (\w+) / (\d+\.?\d*) (\w+)', line)
        if size_match:
            current_size = float(size_match.group(1))
            current_unit = size_match.group(2)
            total_size = float(size_match.group(3))
            total_unit = size_match.group(4)
            
            # Convert to MB for consistent tracking
            if current_unit == "KB":
                current_size /= 1024
            elif current_unit == "GB":
                current_size *= 1024
                
            if total_unit == "KB":
                total_size /= 1024
            elif total_unit == "GB":
                total_size *= 1024
                
            self.current_download["current_size"] = current_size
            self.current_download["total_size"] = total_size
            
            # Calculate speed and remaining time
            if self.current_download["start_time"]:
                elapsed_time = (datetime.now() - self.current_download["start_time"]).total_seconds()
                if elapsed_time > 0:
                    self.current_download["speed"] = current_size / elapsed_time  # MB/s
                    
                    if self.current_download["speed"] > 0:
                        remaining_mb = total_size - current_size
                        remaining_seconds = remaining_mb / self.current_download["speed"]
                        self.current_download["remaining_time"] = timedelta(seconds=int(remaining_seconds))
    
    def download_game(self, game_input, username, password, anonymous=False):
        """Download a game using SteamCMD"""
        game_id = self._extract_game_id(game_input)
        if not game_id:
            return False, "Invalid game ID or URL"
            
        # Reset current download state
        self.current_download = {
            "game_id": game_id,
            "progress": 0,
            "status": "preparing",
            "start_time": datetime.now(),
            "current_size": 0,
            "total_size": 0,
            "speed": 0,
            "remaining_time": None,
            "log": []
        }
        
        game_dir = os.path.join(GAMES_DIR, f"app_{game_id}")
        os.makedirs(game_dir, exist_ok=True)
        
        # Build SteamCMD command
        if anonymous:
            login_cmd = "+login anonymous"
        else:
            login_cmd = f"+login {username} {password}"
            
        download_cmd = f"{login_cmd} +force_install_dir {game_dir} +app_update {game_id} validate +quit"
        
        # Start download process
        try:
            logger.info(f"Starting download for game ID: {game_id}")
            self.current_download["status"] = "downloading"
            
            # Start the process
            self.process = subprocess.Popen(
                [STEAMCMD_EXE] + download_cmd.split(), 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # Start a thread to monitor the process output
            monitor_thread = threading.Thread(target=self._monitor_download_progress)
            monitor_thread.daemon = True
            monitor_thread.start()
            
            return True, "Download started"
            
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            self.current_download["status"] = "error"
            self.current_download["log"].append(f"Error: {str(e)}")
            return False, f"Download error: {str(e)}"
    
    def _monitor_download_progress(self):
        """Monitor the SteamCMD download process and update status"""
        for line in iter(self.process.stdout.readline, ''):
            self.current_download["log"].append(line.strip())
            logger.debug(line.strip())
            
            # Parse progress information
            self._parse_progress(line)
            
            # Check for completion or error
            if "Success!" in line:
                self.current_download["status"] = "completed"
                self.current_download["progress"] = 100
                self._create_public_links()
                
            elif "ERROR!" in line or "Failed" in line:
                self.current_download["status"] = "error"
                
        # Process has ended
        self.process.wait()
        if self.current_download["status"] == "downloading":
            # If it wasn't marked completed or error, but process ended
            self.current_download["status"] = "error"
            self.current_download["log"].append("Process ended unexpectedly")
    
    def _create_public_links(self):
        """Create public links for downloaded files"""
        try:
            game_id = self.current_download["game_id"]
            game_dir = os.path.join(GAMES_DIR, f"app_{game_id}")
            public_game_dir = os.path.join(PUBLIC_DIR, f"app_{game_id}")
            
            # Create a symbolic link or copy files
            if os.path.exists(public_game_dir):
                shutil.rmtree(public_game_dir)
                
            # In Railway, create a symlink to the files
            os.symlink(game_dir, public_game_dir, target_is_directory=True)
            
            # Generate the URLs (assuming Railway's public URL)
            railway_url = os.environ.get("RAILWAY_PUBLIC_URL", "http://localhost:7860")
            public_url = f"{railway_url}/public/app_{game_id}"
            
            # Create a manifest of all the files
            manifest_path = os.path.join(public_game_dir, "manifest.txt")
            with open(manifest_path, 'w') as f:
                for root, dirs, files in os.walk(game_dir):
                    rel_path = os.path.relpath(root, game_dir)
                    for file in files:
                        file_path = os.path.join(rel_path, file)
                        if file_path != "manifest.txt":
                            f.write(f"{file_path}\n")
            
            self.public_links = [
                {
                    "name": "Game Files Directory",
                    "url": public_url
                },
                {
                    "name": "Game Files Manifest",
                    "url": f"{public_url}/manifest.txt"
                }
            ]
            
            logger.info(f"Public links created for game ID {game_id}")
            
        except Exception as e:
            logger.error(f"Failed to create public links: {str(e)}")
            self.current_download["log"].append(f"Failed to create public links: {str(e)}")
    
    def get_download_status(self):
        """Get the current download status"""
        status = dict(self.current_download)
        
        # Add elapsed time
        if status["start_time"]:
            status["elapsed_time"] = str(datetime.now() - status["start_time"]).split('.')[0]
        else:
            status["elapsed_time"] = "00:00:00"
            
        # Format remaining time
        if status["remaining_time"]:
            status["remaining_time"] = str(status["remaining_time"])
        else:
            status["remaining_time"] = "calculating..."
            
        # Add public links if available
        status["public_links"] = self.public_links
        
        return status
    
    def cancel_download(self):
        """Cancel the current download"""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.current_download["status"] = "cancelled"
            logger.info("Download cancelled")
            return True
        return False

# Initialize the downloader
downloader = SteamCMDDownloader()

# Check SteamCMD at startup
STEAMCMD_INSTALLED = downloader.check_steamcmd_installed()
if STEAMCMD_INSTALLED:
    logger.info("SteamCMD is installed and ready")
else:
    logger.warning("SteamCMD is not installed")

# Gradio Interface Functions
def install_steamcmd_gradio():
    """Install SteamCMD via the Gradio interface"""
    success = downloader.install_steamcmd()
    global STEAMCMD_INSTALLED
    STEAMCMD_INSTALLED = success
    return f"SteamCMD {'successfully installed' if success else 'installation failed'}"

def check_install_status():
    """Check the installation status for Gradio interface"""
    return "SteamCMD is installed and ready" if STEAMCMD_INSTALLED else "SteamCMD is not installed"

def start_download(username, password, game_input, anonymous):
    """Start game download via Gradio"""
    if not STEAMCMD_INSTALLED:
        return "SteamCMD not installed. Please install it first."
    
    # Validate game input
    game_id = downloader._extract_game_id(game_input)
    if not game_id:
        return "Invalid game ID or URL. Please provide a valid Steam app ID or URL."
    
    # Check login first
    login_success, login_message = downloader.login(username, password, anonymous)
    if not login_success:
        return login_message
        
    # Start download
    success, message = downloader.download_game(game_input, username, password, anonymous)
    return message

def update_status():
    """Get the current download status for Gradio updates"""
    status = downloader.get_download_status()
    
    # Format output for Gradio
    if status["status"] == "idle":
        return "No active downloads"
    
    output = f"Status: {status['status'].upper()}\n"
    output += f"Game ID: {status['game_id']}\n"
    output += f"Progress: {status['progress']:.1f}%\n"
    output += f"Size: {status['current_size']:.2f} MB / {status['total_size']:.2f} MB\n"
    output += f"Elapsed Time: {status['elapsed_time']}\n"
    output += f"Remaining Time: {status['remaining_time']}\n"
    
    # Add links if completed
    if status["status"] == "completed" and status["public_links"]:
        output += "\nDownload Complete! Public Links:\n"
        for link in status["public_links"]:
            output += f"- {link['name']}: {link['url']}\n"
    
    return output

def get_progress():
    """Get the current progress percentage for Gradio progress bar"""
    return downloader.current_download["progress"]

def cancel_current_download():
    """Cancel the current download via Gradio"""
    if downloader.cancel_download():
        return "Download cancelled"
    else:
        return "No active download to cancel"

# Create Gradio Interface
with gr.Blocks(title="SteamCMD Downloader") as app:
    gr.Markdown("# SteamCMD Game Downloader")
    
    # System Status
    with gr.Row():
        steamcmd_status = gr.Textbox(label="SteamCMD Status", value=check_install_status())
        install_button = gr.Button("Install SteamCMD")
        
    # Login and Game Info
    with gr.Row():
        with gr.Column():
            username = gr.Textbox(label="Steam Username")
            password = gr.Textbox(label="Steam Password", type="password")
            anonymous = gr.Checkbox(label="Login Anonymously (for free games)")
            
        with gr.Column():
            game_input = gr.Textbox(label="Game ID or URL", placeholder="Enter Steam App ID or URL")
            download_button = gr.Button("Download Game")
            cancel_button = gr.Button("Cancel Download")
    
    # Progress Display
    with gr.Row():
        progress_bar = gr.Slider(minimum=0, maximum=100, value=0, label="Download Progress")
        status_text = gr.Textbox(label="Status", value="No active downloads", lines=10)
        refresh_button = gr.Button("Refresh Status")
    
    # Hook up events
    install_button.click(install_steamcmd_gradio, outputs=steamcmd_status)
    download_button.click(start_download, inputs=[username, password, game_input, anonymous], outputs=status_text)
    cancel_button.click(cancel_current_download, outputs=status_text)
    refresh_button.click(update_status, outputs=status_text)
    refresh_button.click(get_progress, outputs=progress_bar)
    
    # Add message about manual refresh
    gr.Markdown("Click 'Refresh Status' to update download progress and status")

# Launch the app
if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
