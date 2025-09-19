#!/bin/bash

echo "=== Docker Ship Proxy Test Suite ==="
PROXY="http://localhost:8080"

echo "1. Testing HTTP..."
curl -s -o /dev/null -w "HTTP: %{http_code}\n" -x $PROXY http://httpforever.com/

echo "2. Testing HTTPS..."
curl -s -o /dev/null -w "HTTPS: %{http_code}\n" -x $PROXY https://example.com/

echo "3. Testing all HTTP methods..."
curl -s -o /dev/null -w "GET: %{http_code}\n" -x $PROXY https://httpbin.org/get
curl -s -o /dev/null -w "POST: %{http_code}\n" -x $PROXY -X POST -d 'test' https://httpbin.org/post
curl -s -o /dev/null -w "PUT: %{http_code}\n" -x $PROXY -X PUT -d '{"test":1}' -H 'Content-Type: application/json' https://httpbin.org/put
curl -s -o /dev/null -w "DELETE: %{http_code}\n" -x $PROXY -X DELETE https://httpbin.org/delete
curl -s -o /dev/null -w "PATCH: %{http_code}\n" -x $PROXY -X PATCH -d '{"patch":1}' -H 'Content-Type: application/json' https://httpbin.org/patch
curl -s -o /dev/null -w "HEAD: %{http_code}\n" -x $PROXY -I https://httpbin.org/get
curl -s -o /dev/null -w "OPTIONS: %{http_code}\n" -x $PROXY -X OPTIONS https://httpbin.org/get

echo "4. Testing consistency (5 identical requests)..."
for i in {1..5}; do 
  curl -s -o /dev/null -w "Request $i: %{http_code} (%{time_total}s)\n" -x $PROXY https://httpbin.org/get
done

echo "5. Testing sequential processing..."
echo "Starting 3-second delay request..."
time curl -s -x $PROXY https://httpbin.org/delay/3 &
DELAY_PID=$!
sleep 1
echo "Starting immediate request (should wait for first to complete)..."
time curl -s -o /dev/null -x $PROXY https://example.com/
wait $DELAY_PID

echo "=== All tests completed ==="
