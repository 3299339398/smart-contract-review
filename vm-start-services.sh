#!/bin/bash
# 在虚拟机 (192.168.10.128) 上运行此脚本，启动 MySQL、Redis、ChromaDB
# 端口使用非标准端口避免与宿主机冲突

: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD must be set}"
: "${MYSQL_PASSWORD:?MYSQL_PASSWORD must be set}"
: "${REDIS_PASSWORD:?REDIS_PASSWORD must be set}"

# 创建网络
docker network create scr-network 2>/dev/null

# 启动 MySQL (宿主机3307 → 容器3306)
docker stop scr-mysql 2>/dev/null; docker rm scr-mysql 2>/dev/null
docker run -d \
  --name scr-mysql \
  --network scr-network \
  --restart unless-stopped \
  -p 127.0.0.1:3307:3306 \
  -e MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" \
  -e MYSQL_DATABASE=contract_review \
  -e MYSQL_USER=scr_user \
  -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
  -v scr_mysql_data:/var/lib/mysql \
  mysql:8.0

# 启动 Redis (宿主机6380 → 容器6379)
docker stop scr-redis 2>/dev/null; docker rm scr-redis 2>/dev/null
docker run -d \
  --name scr-redis \
  --network scr-network \
  --restart unless-stopped \
  -p 127.0.0.1:6380:6379 \
  redis:7-alpine \
  redis-server --appendonly yes --requirepass "$REDIS_PASSWORD"

# 启动 ChromaDB (宿主机8001 → 容器8000)
docker stop scr-chromadb 2>/dev/null; docker rm scr-chromadb 2>/dev/null
docker run -d \
  --name scr-chromadb \
  --network scr-network \
  --restart unless-stopped \
  -p 127.0.0.1:8001:8000 \
  -e IS_PERSISTENT=TRUE \
  -v scr_chroma_data:/chroma/chroma \
  chromadb/chroma:latest

echo "等待服务启动..."
sleep 15

# 检查状态
echo "=== MySQL ==="
docker exec scr-mysql mysqladmin ping -h localhost -u scr_user -p"$MYSQL_PASSWORD" 2>&1

echo "=== Redis ==="
docker exec scr-redis redis-cli -a "$REDIS_PASSWORD" ping 2>&1

echo "=== ChromaDB ==="
curl -s http://localhost:8001/api/v1/heartbeat 2>&1

echo ""
echo "所有服务已启动完成！"
echo "仅允许在本机访问（如需远程访问，请通过受控隧道）:"
echo "  MySQL:    127.0.0.1:3307"
echo "  Redis:    127.0.0.1:6380"
echo "  ChromaDB: 127.0.0.1:8001"
