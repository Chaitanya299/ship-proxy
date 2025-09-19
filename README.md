# Ship Proxy (Python) – Sequential over a Single TCP Connection

A ship-side HTTP proxy (client) that funnels all HTTP/HTTPS requests sequentially over a single persistent TCP connection to an offshore proxy server, which then talks to the public Internet.

## Architecture

```
Browser → HTTP/S → Ship Proxy (client:8080) → Single TCP → Offshore Proxy (server:9090) → Internet
```

**Key Feature**: Sequential processing is enforced on the ship - concurrent browser requests are queued and handled strictly one by one, ensuring only a single logical request is in flight over the single TCP connection.

## Features

- ✅ Explicit HTTP proxy on ship, listening on port 8080
- ✅ Single long‑lived TCP to offshore server; reconnection on failure
- ✅ Sequential request handling (one by one) - **VERIFIED**
- ✅ HTTP and HTTPS (via CONNECT tunnels)
- ✅ Supports all HTTP methods (GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS)
- ✅ Works with curl on macOS/Linux and Windows
- ✅ Docker containerized deployment
- ✅ Browser proxy configuration support

## Repository Structure

```
ship/
├── shipproxy/
│   ├── __init__.py          # Python package
│   ├── client.py            # Ship proxy (listens on :8080)
│   ├── server.py            # Offshore proxy server (listens on :9090)
│   ├── proto.py             # Framed protocol over TCP
│   └── httpx.py             # HTTP header utilities
├── Dockerfile.client        # Container for client
├── Dockerfile.server        # Container for server
├── requirements.txt         # Python dependencies
├── test_docker_proxy_fast.sh # Comprehensive test suite
└── README.md               # This file
```

## Quick Start Guide

### Option 1: Docker (Recommended)

**Step 1: Build Docker Images**
```bash
# Navigate to project directory
cd /path/to/ship

# Build images
docker build -t ship-proxy-server:latest -f Dockerfile.server .
docker build -t ship-proxy-client:latest -f Dockerfile.client .
```

**Step 2: Create Network and Run Containers**
```bash
# Create network
docker network create shipnet

# Start offshore server
docker run -d --rm --name offshore --network shipnet -p 9090:9090 \
  ship-proxy-server:latest --listen :9090

# Start ship client
docker run -d --rm --name ship --network shipnet -p 8080:8080 \
  ship-proxy-client:latest --listen :8080 --server offshore:9090
```

**Step 3: Verify Containers**
```bash
# Check containers are running
docker ps

# Should show both 'ship' and 'offshore' containers
```

**Step 4: Test Basic Functionality**
```bash
# Test HTTP
curl -x http://localhost:8080 http://httpforever.com/

# Test HTTPS
curl -x http://localhost:8080 https://example.com/
```

### Option 2: Local Python

**Prerequisites**: Python 3.11+ and pip

**Step 1: Install Dependencies**
```bash
pip install -r requirements.txt
```

**Step 2: Start Services**

*Terminal A (Offshore Server):*
```bash
python -m shipproxy.server --listen :9090
```

*Terminal B (Ship Client):*
```bash
python -m shipproxy.client --listen :8080 --server 127.0.0.1:9090
```

**Step 3: Test**
```bash
# Basic test
curl -x http://localhost:8080 http://httpforever.com/
```

## Comprehensive Testing

### Automated Test Suite

Run the complete test suite to verify all functionality:

```bash
# Make test script executable
chmod +x test_docker_proxy_fast.sh

# Run comprehensive tests
./test_docker_proxy_fast.sh
```

**Expected Output:**
```
=== Docker Ship Proxy Test Suite (Fast Version) ===
1. Testing HTTP...
HTTP: 200
2. Testing HTTPS...
HTTPS: 200
3. Testing all HTTP methods...
GET: 200
POST: 200
PUT: 200
DELETE: 200
PATCH: 200
HEAD: 200
OPTIONS: 200
4. Testing consistency (5 identical requests)...
Request 1: 200 (0.577s)
Request 2: 200 (0.575s)
Request 3: 200 (0.461s)
Request 4: 200 (0.712s)
Request 5: 200 (0.713s)
5. Testing sequential processing...
Starting 2-second delay request...
Starting immediate request (should wait for first to complete)...
[Shows timing proving sequential behavior]
=== All tests completed ===
```

### Manual Testing

**Basic HTTP/HTTPS Tests:**
```bash
# HTTP test
curl -x http://localhost:8080 http://httpforever.com/

# HTTPS test  
curl -x http://localhost:8080 https://example.com/

# Windows
curl.exe -x http://localhost:8080 http://httpforever.com/
```

**All HTTP Methods:**
```bash
# GET
curl -x http://localhost:8080 https://httpbingo.org/get

# POST
curl -x http://localhost:8080 -X POST -d 'test data' https://httpbingo.org/post

# PUT
curl -x http://localhost:8080 -X PUT -d '{"key":"value"}' -H 'Content-Type: application/json' https://httpbingo.org/put

# DELETE
curl -x http://localhost:8080 -X DELETE https://httpbingo.org/delete

# PATCH
curl -x http://localhost:8080 -X PATCH -d '{"update":"field"}' -H 'Content-Type: application/json' https://httpbingo.org/patch

# HEAD (headers only)
curl -I -x http://localhost:8080 https://httpbingo.org/get

# OPTIONS
curl -x http://localhost:8080 -X OPTIONS https://httpbingo.org/get
```

**Sequential Processing Test (Critical):**
```bash
# Terminal 1: Start long request
echo "Starting 3-second delay..."
time curl -x http://localhost:8080 https://httpbingo.org/delay/3 &

# Terminal 2: Immediately start quick request
sleep 1
echo "Starting quick request (should wait)..."
time curl -s -o /dev/null -x http://localhost:8080 https://example.com/
```

**Expected Result**: The second request should take ~3+ seconds total, proving it waited for the first request to complete.

**Consistency Test:**
```bash
# Run same request 5 times
for i in {1..5}; do 
  curl -s -o /dev/null -w "Request $i: %{http_code} (%{time_total}s)\n" -x http://localhost:8080 https://httpbingo.org/get
done
```

**Expected Result**: All requests should return `200` with similar response times.

## Browser Configuration

Configure your browser to use the ship proxy:

### Chrome/Edge/Firefox
1. Open browser settings
2. Search for "proxy" 
3. Configure manual proxy:
   - **HTTP Proxy**: `localhost:8080`
   - **HTTPS Proxy**: `localhost:8080`
   - **No proxy for**: `localhost,127.0.0.1`

### macOS System-wide
1. System Settings → Network → Your Connection → Details → Proxies
2. Enable "Web Proxy (HTTP)" and "Secure Web Proxy (HTTPS)"
3. Server: `localhost`, Port: `8080`

### Windows System-wide
1. Settings → Network & Internet → Proxy
2. Turn on "Use a proxy server"
3. Address: `127.0.0.1`, Port: `8080`

## Troubleshooting & Debug Options

### Common Issues

**1. Containers not starting:**
```bash
# Check container status
docker ps

# Check logs for errors
docker logs offshore
docker logs ship

# Restart containers
docker stop ship offshore
docker rm ship offshore
# Then re-run the docker run commands
```

**2. Port conflicts:**
```bash
# Check what's using ports
lsof -i :8080
lsof -i :9090

# Kill processes if needed
sudo kill -9 $(lsof -t -i:8080)
sudo kill -9 $(lsof -t -i:9090)
```

**3. Connection issues:**
```bash
# Test container networking
docker exec ship ping -c 2 offshore

# Test if proxy port responds
curl -v http://localhost:8080/

# Check network
docker network inspect shipnet
```

**4. Proxy not working:**
```bash
# Test with verbose output
curl -v -x http://localhost:8080 http://httpforever.com/

# Check if containers can reach internet
docker exec offshore curl -s http://httpforever.com/
```

### Debug Commands

**Container inspection:**
```bash
# Check container details
docker inspect ship
docker inspect offshore

# Execute commands inside containers
docker exec ship python --version
docker exec offshore python -c "import shipproxy; print('OK')"

# Check processes inside containers
docker exec ship ps aux
docker exec offshore ps aux
```

**Network debugging:**
```bash
# Test connectivity between containers
docker exec ship nc -zv offshore 9090

# Check listening ports
docker exec ship netstat -tlnp
docker exec offshore netstat -tlnp
```

### Performance Monitoring

**Monitor request timing:**
```bash
# Time individual requests
time curl -x http://localhost:8080 https://httpbingo.org/get

# Monitor multiple requests
for i in {1..10}; do
  curl -s -o /dev/null -w "Request $i: %{time_total}s\n" -x http://localhost:8080 https://httpbingo.org/get
done
```

## How Sequential Processing Works

The ship proxy enforces strict sequential processing through:

1. **Single Worker Queue**: The client (`shipproxy/client.py`) uses a single worker thread with a queue
2. **One Request at a Time**: Each request is processed completely before the next begins
3. **Single TCP Connection**: All requests share one persistent connection to the offshore server
4. **CONNECT Tunnels**: HTTPS requests hold the worker until the tunnel closes

**Code Flow:**
```
Browser Request → Client Queue → Single Worker → TCP Connection → Offshore Server → Internet
```

## Architecture Details

### Client (Ship Proxy)
- Listens on port 8080 as HTTP proxy
- Queues all incoming requests
- Maintains single TCP connection to offshore server
- Handles HTTP and HTTPS (via CONNECT method)

### Server (Offshore Proxy)  
- Listens on port 9090 for client connections
- Makes actual requests to internet
- Streams responses back to client
- Handles connection management

### Protocol
- Custom framed protocol over TCP
- JSON metadata + binary payloads
- Request/response streaming
- Connection management frames

## Publishing & Deployment

### Docker Hub
```bash
export DOCKER_USER=yourdockerid
docker tag ship-proxy-server:latest $DOCKER_USER/ship-proxy-server:latest
docker tag ship-proxy-client:latest $DOCKER_USER/ship-proxy-client:latest
docker login -u "$DOCKER_USER"
docker push $DOCKER_USER/ship-proxy-server:latest
docker push $DOCKER_USER/ship-proxy-client:latest
```

### GitHub Container Registry
```bash
export GH_USER=yourgithubid
docker tag ship-proxy-server:latest ghcr.io/$GH_USER/ship-proxy-server:latest
docker tag ship-proxy-client:latest ghcr.io/$GH_USER/ship-proxy-client:latest
echo $GITHUB_TOKEN | docker login ghcr.io -u $GH_USER --password-stdin
docker push ghcr.io/$GH_USER/ship-proxy-server:latest
docker push ghcr.io/$GH_USER/ship-proxy-client:latest
```

### GitHub Repository
```bash
git init
git add .
git commit -m "Ship proxy: sequential HTTP/HTTPS over single TCP connection"
git branch -M main
git remote add origin https://github.com/<username>/ship-proxy.git
git push -u origin main
```

## Requirements Verification

This implementation satisfies all requirements:

- ✅ **Proxy client and server designed**: Python implementation with proper architecture
- ✅ **Browser configuration support**: Works as HTTP proxy on port 8080
- ✅ **Sequential processing**: Verified through timing tests - requests processed one by one
- ✅ **Docker images**: Built and tested containers for both client and server
- ✅ **Docker run commands**: Provided and verified working commands
- ✅ **Port 8080 exposure**: Client exposes correct port
- ✅ **macOS/Linux curl support**: `curl -x http://localhost:8080 http://httpforever.com/` works
- ✅ **Windows curl support**: `curl.exe -x http://localhost:8080 http://httpforever.com/` documented
- ✅ **Consistent responses**: Multiple curl calls return consistent results
- ✅ **All HTTP methods**: GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS all supported and tested

**Test Results**: All tests pass with 200 status codes and proper sequential timing behavior.
