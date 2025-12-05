#!/bin/bash

###
# Инициализируем бд
###

#!/usr/bin/env bash
set -euo pipefail

echo "Initializing MongoDB config server replica set..."
docker compose exec -T configSrv mongosh --port 27017 --quiet <<EOF
let initiated = false;
try {
  const status = rs.status();
  initiated = status.ok === 1;
} catch (e) {
  // NotYetInitialized: first run, safe to initiate
  if (e.codeName !== "NotYetInitialized" && e.code !== 94) {
    throw e;
  }
}
if (!initiated) {
  rs.initiate({
    _id: "config_server",
    configsvr: true,
    members: [
      { _id: 0, host: "configSrv:27017" },
      { _id: 1, host: "configSrvReplica1:27016" },
      { _id: 2, host: "configSrvReplica2:27015" }
    ]
  });
  print("config_server replica set initialized");
} else {
  print("config_server replica set already initialized, skipping");
}
EOF

echo "Initializing shard1 replica set..."
docker compose exec -T shard1 mongosh --port 27018 --quiet <<EOF
let initiated = false;
try {
  const status = rs.status();
  initiated = status.ok === 1;
} catch (e) {
  if (e.codeName !== "NotYetInitialized" && e.code !== 94) {
    throw e;
  }
}
if (!initiated) {
  rs.initiate({
    _id: "shard1",
    members: [
      { _id: 0, host: "shard1:27018" }
    ]
  });
  print("shard1 replica set initialized");
} else {
  print("shard1 replica set already initialized, skipping");
}
EOF

echo "Initializing shard2 replica set..."
docker compose exec -T shard2 mongosh --port 27019 --quiet <<EOF
let initiated = false;
try {
  const status = rs.status();
  initiated = status.ok === 1;
} catch (e) {
  if (e.codeName !== "NotYetInitialized" && e.code !== 94) {
    throw e;
  }
}
if (!initiated) {
  rs.initiate({
    _id: "shard2",
    members: [
      { _id: 1, host: "shard2:27019" }
    ]
  });
  print("shard2 replica set initialized");
} else {
  print("shard2 replica set already initialized, skipping");
}
EOF

echo "Configuring mongos router and adding shards..."
echo "Waiting for mongos_router to be ready..."
docker compose exec -T mongos_router sh -c '
i=0
max_retries=30
until mongosh --port 27020 --quiet --eval "db.adminCommand({ ping: 1 })" >/dev/null 2>&1; do
  i=$((i+1))
  if [ "$i" -ge "$max_retries" ]; then
    echo "mongos_router did not become ready in time" >&2
    exit 1
  fi
  echo "Waiting for mongos_router to be ready ($i/$max_retries)..."
  sleep 2
done
'
docker compose exec -T mongos_router mongosh --port 27020 --quiet <<EOF
const existingShardsRes = db.adminCommand({ listShards: 1 });
if (!existingShardsRes.ok) {
  throw new Error("Failed to list shards: " + tojson(existingShardsRes));
}
const existingShardIds = existingShardsRes.shards.map(s => s._id);

if (!existingShardIds.includes("shard1")) {
  sh.addShard("shard1/shard1:27018");
  print("Added shard1");
} else {
  print("shard1 already present, skipping sh.addShard");
}

if (!existingShardIds.includes("shard2")) {
  sh.addShard("shard2/shard2:27019");
  print("Added shard2");
} else {
  print("shard2 already present, skipping sh.addShard");
}

sh.enableSharding("somedb");
sh.shardCollection("somedb.helloDoc", { "name" : "hashed" } )
EOF

echo "Mongo sharding initialization completed."


echo "Creating fake data..."

docker compose exec -T mongos_router mongosh --port 27020 --quiet <<EOF
use somedb
for(var i = 0; i < 1000; i++) db.helloDoc.insertOne({age:i, name:"ly"+i})
EOF
