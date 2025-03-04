FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    tar \
    lib32gcc-s1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create directories and install SteamCMD
RUN mkdir -p /app/steamcmd && \
    curl -sSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz | tar -xz -C /app/steamcmd && \
    chmod +x /app/steamcmd/steamcmd.sh && \
    /app/steamcmd/steamcmd.sh +quit # Auto-update on build

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create other necessary directories
RUN mkdir -p games public

# Expose port for Gradio
EXPOSE 7860

# Start the application
CMD ["python", "path/to/your/file.py"]