# Docker Setup Guide

## Prerequisites

### Mac Development
```bash
# Install Docker Desktop for Mac
brew install --cask docker
# Or download from https://www.docker.com/products/docker-desktop/
```

### Windows Usage
```bash
# Install Docker Desktop for Windows
# Download from https://www.docker.com/products/docker-desktop/
```

## Usage

### Mac (Development)
```bash
# Allow X11 forwarding for GUI
xhost +localhost

# Build and start services
docker-compose up --build

# Run in background
docker-compose up -d --build
```

### Windows (Production)
```bash
# Start services
docker-compose up --build

# Access GUI via VNC at localhost:5900
# Use VNC viewer like TightVNC or RealVNC
```

## Commands

```bash
# Build only
docker-compose build

# View logs
docker-compose logs -f gmail-monitor
docker-compose logs -f client

# Stop services
docker-compose down

# Clean up
docker-compose down --volumes --rmi all
```

## Environment Variables

Ensure your `.env` file contains:
```
# Gmail settings
GMAIL_USER=your-email@gmail.com
GMAIL_PASSWORD=your-app-password

# MQTT settings  
MQTT_HOST=your-mqtt-host
MQTT_PORT=8883
MQTT_USER=your-user
MQTT_PASS=your-password
```

## Troubleshooting

### Mac GUI Issues
- Run `xhost +localhost` before starting
- Ensure XQuartz is installed and running

### Windows GUI Access
- Connect VNC client to `localhost:5900`
- No password required (container access)

### Container Issues
```bash
# Rebuild without cache
docker-compose build --no-cache

# Enter container for debugging  
docker-compose exec gmail-monitor /bin/sh
docker-compose exec client /bin/bash
```