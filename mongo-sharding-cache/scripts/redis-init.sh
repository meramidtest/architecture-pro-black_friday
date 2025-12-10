docker compose exec -T redis_1 /bin/sh <<EOF
echo "yes" | redis-cli --cluster create   173.17.0.16:6379   173.17.0.17:6379   173.17.0.18:6379   173.17.0.19:6379   173.17.0.20:6379   173.17.0.21:6379   --cluster-replicas 1
EOF
