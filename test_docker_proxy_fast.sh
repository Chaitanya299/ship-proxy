#!/bin/bash

echo "=== Docker Ship Proxy Test Suite (Fast Version) ==="
PROXY="http://localhost:8080"

echo "1. Testing HTTP..."
curl -s -o /dev/null -w "HTTP: %{http_code}\n" -x $PROXY http://example.com/

echo "2. Testing HTTPS..."
curl -s -o /dev/null -w "HTTPS: %{http_code}\n" -x $PROXY https://example.com/

echo "3. Testing all HTTP methods..."
curl -s -o /dev/null -w "GET: %{http_code}\n" -x $PROXY https://httpbingo.org/get
curl -s -o /dev/null -w "POST: %{http_code}\n" -x $PROXY -X POST -d 'test' https://httpbingo.org/post
curl -s -o /dev/null -w "PUT: %{http_code}\n" -x $PROXY -X PUT -d '{"test":1}' -H 'Content-Type: application/json' https://httpbingo.org/put
curl -s -o /dev/null -w "DELETE: %{http_code}\n" -x $PROXY -X DELETE https://httpbingo.org/delete
curl -s -o /dev/null -w "PATCH: %{http_code}\n" -x $PROXY -X PATCH -d '{"patch":1}' -H 'Content-Type: application/json' https://httpbingo.org/patch
curl -s -o /dev/null -w "HEAD: %{http_code}\n" -x $PROXY -I https://httpbingo.org/get
curl -s -o /dev/null -w "OPTIONS: %{http_code}\n" -x $PROXY -X OPTIONS https://httpbingo.org/get

echo "4. Testing consistency (5 identical requests)..."
for i in {1..5}; do 
  curl -s -o /dev/null -w "Request $i: %{http_code} (%{time_total}s)\n" -x $PROXY https://httpbingo.org/get
done

echo "5. Testing sequential processing..."
echo "Starting 2-second delay request..."
time curl -s -x $PROXY https://httpbingo.org/delay/2 &
DELAY_PID=$!
sleep 0.5
echo "Starting immediate request (should wait for first to complete)..."
time curl -s -o /dev/null -x $PROXY https://example.com/
wait $DELAY_PID

echo "=== All tests completed ==="
