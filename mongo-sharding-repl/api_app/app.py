import json
import logging
import os
import time
from typing import List, Optional

import motor.motor_asyncio
from bson import ObjectId
from fastapi import Body, FastAPI, HTTPException, status
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache
from logmiddleware import RouterLoggingMiddleware, logging_config
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.functional_validators import BeforeValidator
from pymongo import errors
from redis import asyncio as aioredis
from typing_extensions import Annotated

# Configure JSON logging
logging.config.dictConfig(logging_config)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(
    RouterLoggingMiddleware,
    logger=logger,
)

DATABASE_URL = os.environ["MONGODB_URL"]
DATABASE_NAME = os.environ["MONGODB_DATABASE_NAME"]
REDIS_URL = os.getenv("REDIS_URL", None)


def nocache(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


if REDIS_URL:
    cache = cache
else:
    cache = nocache


client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
db = client[DATABASE_NAME]

# Represents an ObjectId field in the database.
# It will be represented as a `str` on the model so that it can be serialized to JSON.
PyObjectId = Annotated[str, BeforeValidator(str)]


@app.on_event("startup")
async def startup():
    if REDIS_URL:
        redis = aioredis.from_url(REDIS_URL, encoding="utf8", decode_responses=True)
        FastAPICache.init(RedisBackend(redis), prefix="api:cache")


class UserModel(BaseModel):
    """
    Container for a single user record.
    """

    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    age: int = Field(...)
    name: str = Field(...)


class UserCollection(BaseModel):
    """
    A container holding a list of `UserModel` instances.
    """

    users: List[UserModel]


@app.get("/")
async def root():
    collection_names = await db.list_collection_names()
    collections = {}
    # Aggregate total documents per shard across all collections (if sharded)
    documents_per_shard: dict[str, int] = {}
    total_documents = 0
    for collection_name in collection_names:
        collection = db.get_collection(collection_name)
        total_count = await collection.count_documents({})
        total_documents += total_count

        per_shard_counts = None
        # For sharded clusters, collStats contains a "shards" section with per-shard stats
        try:
            coll_stats = await db.command({"collStats": collection_name})
            shards_stats = coll_stats.get("shards")
            if shards_stats:
                per_shard_counts = {
                    shard_name: shard_info.get("count", 0)
                    for shard_name, shard_info in shards_stats.items()
                }
                # Update global per-shard totals
                for shard_name, count in per_shard_counts.items():
                    documents_per_shard[shard_name] = (
                        documents_per_shard.get(shard_name, 0) + count
                    )
        except errors.OperationFailure:
            # collStats might fail in some configurations; ignore per-shard stats in that case
            per_shard_counts = None

        collections[collection_name] = {
            "documents_count": total_count,
            "documents_per_shard": per_shard_counts,
        }
    try:
        replica_status = await client.admin.command("replSetGetStatus")
        replica_status = json.dumps(replica_status, indent=2, default=str)
    except errors.OperationFailure:
        replica_status = "No Replicas"

    topology_description = client.topology_description
    read_preference = client.client_options.read_preference
    topology_type = topology_description.topology_type_name
    replicaset_name = topology_description.replica_set_name

    shards = None
    if topology_type == "Sharded":
        shards_list = await client.admin.command("listShards")
        shards = {}
        for shard in shards_list.get("shards", {}):
            shards[shard["_id"]] = shard["host"]

        expanded_documents_per_shard: dict[str, int] = {}
        expanded_documents_per_shard.update(documents_per_shard)

        for shard_name, host_string in shards.items():
            # Extract the comma‑separated list of hosts
            hosts_part = host_string.split("/", 1)[1] if "/" in host_string else host_string
            hosts = hosts_part.split(",") if hosts_part else []
            shard_docs = documents_per_shard.get(shard_name, 0)

            for host in hosts:
                host = host.strip()
                if not host:
                    continue
                key = f"{shard_name}/{host}"
                expanded_documents_per_shard[key] = shard_docs

        documents_per_shard = expanded_documents_per_shard

    config_servers = None
    try:
        # On mongos, getCmdLineOpts contains the --configdb value with config server hosts
        cmdline_opts = await client.admin.command({"getCmdLineOpts": 1})
        parsed_opts = cmdline_opts.get("parsed", {})
        configdb = parsed_opts.get("configdb")
        if isinstance(configdb, str):
            # configdb format: "<replSetName>/<host1>,<host2>,<host3>"
            try:
                _, hosts_part = configdb.split("/", 1)
            except ValueError:
                hosts_part = configdb
            config_servers = hosts_part.split(",") if hosts_part else []
    except errors.OperationFailure:
        config_servers = None

    cache_enabled = False
    if REDIS_URL:
        cache_enabled = FastAPICache.get_enable()

    return {
        "mongo_topology_type": topology_type,
        "mongo_replicaset_name": replicaset_name,
        "mongo_db": DATABASE_NAME,
        "mongo_total_documents": total_documents,
        "read_preference": str(read_preference),
        "mongo_nodes": client.nodes,
        "mongo_primary_host": client.primary,
        "mongo_secondary_hosts": client.secondaries,
        "mongo_is_primary": client.is_primary,
        "mongo_is_mongos": client.is_mongos,
        "collections": collections,
        "shards": shards,
        "documents_per_shard": documents_per_shard or None,
        "config_servers": config_servers,
        "cache_enabled": cache_enabled,
        "status": "OK",
    }


@app.get("/{collection_name}/count")
async def collection_count(collection_name: str):
    collection = db.get_collection(collection_name)
    items_count = await collection.count_documents({})
    # status = await client.admin.command('replSetGetStatus')
    # import ipdb; ipdb.set_trace()
    return {"status": "OK", "mongo_db": DATABASE_NAME, "items_count": items_count}


@app.get(
    "/{collection_name}/users",
    response_description="List all users",
    response_model=UserCollection,
    response_model_by_alias=False,
)
@cache(expire=60 * 1)
async def list_users(collection_name: str):
    """
    List all of the user data in the database.
    The response is unpaginated and limited to 1000 results.
    """
    time.sleep(1)
    collection = db.get_collection(collection_name)
    return UserCollection(users=await collection.find().to_list(1000))


@app.get(
    "/{collection_name}/users/{name}",
    response_description="Get a single user",
    response_model=UserModel,
    response_model_by_alias=False,
)
async def show_user(collection_name: str, name: str):
    """
    Get the record for a specific user, looked up by `name`.
    """

    collection = db.get_collection(collection_name)
    if (user := await collection.find_one({"name": name})) is not None:
        return user

    raise HTTPException(status_code=404, detail=f"User {name} not found")


@app.post(
    "/{collection_name}/users",
    response_description="Add new user",
    response_model=UserModel,
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=False,
)
async def create_user(collection_name: str, user: UserModel = Body(...)):
    """
    Insert a new user record.

    A unique `id` will be created and provided in the response.
    """
    collection = db.get_collection(collection_name)
    new_user = await collection.insert_one(
        user.model_dump(by_alias=True, exclude=["id"])
    )
    created_user = await collection.find_one({"_id": new_user.inserted_id})
    return created_user
