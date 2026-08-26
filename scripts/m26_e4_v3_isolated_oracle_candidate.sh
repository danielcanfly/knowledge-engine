#!/usr/bin/env bash
set -euo pipefail

BASE_CONTAINER='m26-public-api-production-repair2-ownerhash-r2-auth-520aed'
BASE_IMAGE='knowledge-engine:m26-public-api-staging-repair2-520aed'
BASE_IMAGE_ID='sha256:7b2bdc32a3ed769f068b885e171fe31da10f33f1335b778b8bfb89ccb1523919'
ACCEPTED_RUNTIME_ID='520aeddb0566ca0ed1e2b74fa1fea1b7504a5e87'
SEMANTIC_CONTRACT_FINGERPRINT='8d1a1f690c8e0d8ba5d39f772ce6146572286f2fe510a799e9848625e074128d'
CANDIDATE_IMAGE='knowledge-engine:m26-e4-v3-candidate-180'
CANDIDATE_CONTAINER='m26-e4-v3-candidate-180'
CANDIDATE_PORT='18088'
RELEASE_ID='m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440'
DIRECT_MANIFEST_KEY="releases/${RELEASE_ID}/manifest.json"
DIRECT_MANIFEST_SHA='05e5f33e454e2ec5723223862b91729b9e4cb3f3c93068b5533eacae3e699796'
CANDIDATE_PROMOTION_KEY="candidate-bindings/${RELEASE_ID}/promotion-manifest.json"
CANDIDATE_POINTER_KEY="candidate-bindings/${RELEASE_ID}/pointer.json"
CANDIDATE_POINTER_SHA='5e4a2b995519fdae06b94bbcd5243ac8412c77b2e65b9286868ef58b7f06e574'
QDRANT_COLLECTION='m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440'
EXPECTED_SOURCE_SHA='f5e20062c1400d7320fe2dbecf6409a0a8c910a7'
EXPECTED_ADMISSION_SHA='ec79a3cad1d84a936a6420b64c3ec43859ebd296eee992b2654dd8537d62da2d'
EXPECTED_GRAPH_V2_SHA='d46022c9a4f50c939fd5f641b3073aee273a0cee690f4d7cadea2374698e2f14'
EXPECTED_SOURCE_COUNT='180'
EXPECTED_SEMANTIC_COUNT='4424'
EXPECTED_NODE_COUNT='4457'
EXPECTED_EDGE_COUNT='8995'
WORKDIR='/tmp/m26-e4-v3-candidate-build'
ENVFILE='/tmp/m26-e4-v3-candidate.env'
OPENAPI='/tmp/m26-e4-v3-openapi.json'

cleanup() {
  rm -rf "$WORKDIR" "$ENVFILE" "$OPENAPI"
}
trap cleanup EXIT

fail() {
  echo "$1" >&2
  exit "${2:-1}"
}

# --- Gate A: exact frozen production base, before any candidate mutation ---
docker inspect "$BASE_CONTAINER" >/dev/null 2>&1 || fail 'M26_E4_V3_FROZEN_BASE_CONTAINER_MISSING' 3
test "$(docker inspect -f '{{.State.Running}}' "$BASE_CONTAINER")" = 'true' || fail 'M26_E4_V3_FROZEN_BASE_CONTAINER_NOT_RUNNING' 3
OBSERVED_BASE_IMAGE_ID="$(docker inspect -f '{{.Image}}' "$BASE_CONTAINER")"
test "$OBSERVED_BASE_IMAGE_ID" = "$BASE_IMAGE_ID" || fail "M26_E4_V3_BASE_IMAGE_ID_MISMATCH expected=$BASE_IMAGE_ID observed=$OBSERVED_BASE_IMAGE_ID" 3
TAG_IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$BASE_IMAGE")"
test "$TAG_IMAGE_ID" = "$BASE_IMAGE_ID" || fail "M26_E4_V3_BASE_TAG_DRIFT expected=$BASE_IMAGE_ID observed=$TAG_IMAGE_ID" 3
test "$(docker port "$BASE_CONTAINER" 8080/tcp)" = '127.0.0.1:18087' || fail 'M26_E4_V3_PRODUCTION_PORT_BINDING_DRIFT' 3

PROD_ID_BEFORE="$(docker inspect -f '{{.Id}}' "$BASE_CONTAINER")"
PROD_STARTED_BEFORE="$(docker inspect -f '{{.State.StartedAt}}' "$BASE_CONTAINER")"
PROD_RESTART_BEFORE="$(docker inspect -f '{{.RestartCount}}' "$BASE_CONTAINER")"
PROD_POINTER_SHA_BEFORE="$(docker exec "$BASE_CONTAINER" python -c 'from knowledge_engine.config import Settings; from knowledge_engine.storage import create_object_store,sha256_bytes; print(sha256_bytes(create_object_store(Settings.from_env()).get("channels/production.json")))')"

RUNTIME_ID="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$BASE_CONTAINER" | awk -F= '$1=="M26_ACCEPTED_RUNTIME_CANDIDATE" {sub(/^[^=]*=/,""); print; exit}')"
test "$RUNTIME_ID" = "$ACCEPTED_RUNTIME_ID" || fail "M26_E4_V3_ACCEPTED_RUNTIME_ID_MISMATCH expected=$ACCEPTED_RUNTIME_ID observed=$RUNTIME_ID" 4
FINGERPRINT="$(docker exec "$BASE_CONTAINER" python -c 'from knowledge_engine.m26_aq_semantic_contract import semantic_contract_fingerprint; print(semantic_contract_fingerprint())')"
test "$FINGERPRINT" = "$SEMANTIC_CONTRACT_FINGERPRINT" || fail "M26_E4_V3_SEMANTIC_FINGERPRINT_MISMATCH expected=$SEMANTIC_CONTRACT_FINGERPRINT observed=$FINGERPRINT" 4

python3 - <<'PY'
import json, subprocess
base='m26-public-api-production-repair2-ownerhash-r2-auth-520aed'
frozen={
 'knowledge_engine.m26_aq_semantic_contract':'4f5f9f0795ec6b0861590c4e9ed8b6861c7f02c2c0c918c2fec61d7b1113ae22',
 'knowledge_engine.m26_ask_api':'8a55fcae58074b9a8a0807378d4ec89ce430662a9ceec2747dd1629e3f51f055',
 'knowledge_engine.m26_cloudflare_provider_router':'faba920a5ac10bade89ab47732cc76b3a817bfed66c4a5c8ced8ec55dc4bab88',
 'knowledge_engine.m26_pa5_v8_live':'91ffbfa8113548cbee1190ac9b2196524acd364f2c95029a06a66f26fb0c3060',
 'knowledge_engine.m26_pa7_arbitrary_query_runtime':'4a9e3ca5f1447a79739db3bd1c9cfd4a5710a358a8e45fef43aaef5d16a2a116',
 'knowledge_engine.m26_production_answer_bundle':'d687b4ccd0fe11b51ef0887a604f4451bf99eac8f70d43fa23d09bb60b4c5f0c',
 'knowledge_engine.m26_production_api':'ff83ef35d14c878a53523b0109673e3c921c238e165aeb9d1b2f1a6f9f44ba20',
 'knowledge_engine.m26_verified_answer_citation_gate':'716fbef1b53eb06f62ff47a96adfb10c70b4f50db30a2f01107def99a09e4708',
 'knowledge_engine.m26_multilingual_runtime':'8562a8d7759835abe1223c515d22f86b9482936b83a7ff7b2b21028b5c9699f5',
 'knowledge_engine.m26_translation_gateway':'3146080fd4d8b0778986c881ef76b252030b3896a1c5974863bfb58fddf7c541',
 'knowledge_engine.m26_translation_gateway_public_api':'0c1f36489bc38b1c7fe786949a6dee76aadeb3a7fac2e299757902464ca2e9f2',
 'knowledge_engine.m26_translation_invariants':'a925ddaa756a60d7031936c0671c45b23893fa38d205722557bd1d98ad5c387c',
}
code='''import importlib,hashlib,json,pathlib\nmods=%r\nout={}\nfor n in mods:\n p=pathlib.Path(importlib.import_module(n).__file__).resolve(); out[n]=hashlib.sha256(p.read_bytes()).hexdigest()\nprint(json.dumps(out,sort_keys=True))''' % list(frozen)
observed=json.loads(subprocess.run(['docker','exec',base,'python','-c',code],text=True,capture_output=True,check=True).stdout)
if observed != frozen:
    raise SystemExit('M26_E4_V3_FROZEN_MODULE_HASH_MISMATCH '+json.dumps({'expected':frozen,'observed':observed},sort_keys=True))
print(json.dumps({'status':'M26_E4_V3_FROZEN_SEMANTIC_BYTES_PASS','module_hashes':observed},sort_keys=True))
PY

if ss -ltnH | awk '{print $4}' | grep -Eq "(^|:)${CANDIDATE_PORT}$"; then
  if ! docker ps --format '{{.Names}}' | grep -Fxq "$CANDIDATE_CONTAINER"; then
    fail "M26_E4_V3_CANDIDATE_PORT_OCCUPIED port=$CANDIDATE_PORT" 3
  fi
fi

# --- Gate B: derived image adds only binding bootstrap; frozen modules stay byte-identical ---
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"
cat > "$WORKDIR/m26_e4_binding_overlay.py" <<'PY'
"""M26 E4 V3 binding-only startup overlay. No accepted runtime implementation is replaced."""
import knowledge_engine.m26_production_answer_bundle as b
RELEASE_ID='m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440'
b.FULL_PRODUCTION_RELEASE_ID=RELEASE_ID
b.FULL_PRODUCTION_MANIFEST_KEY=f'releases/{RELEASE_ID}/manifest.json'
b.FULL_PRODUCTION_PROMOTION_MANIFEST_KEY=f'candidate-bindings/{RELEASE_ID}/promotion-manifest.json'
b.FULL_PRODUCTION_PROMOTION_MANIFEST_SHA256='05e5f33e454e2ec5723223862b91729b9e4cb3f3c93068b5533eacae3e699796'
b.FULL_PRODUCTION_GRAPH_V2_SHA256='d46022c9a4f50c939fd5f641b3073aee273a0cee690f4d7cadea2374698e2f14'
b.FULL_PRODUCTION_POINTER_KEY=f'candidate-bindings/{RELEASE_ID}/pointer.json'
b.FULL_PRODUCTION_POINTER_SHA256='5e4a2b995519fdae06b94bbcd5243ac8412c77b2e65b9286868ef58b7f06e574'
b.FULL_PRODUCTION_QDRANT_COLLECTION='m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440'
b.FULL_PRODUCTION_NODE_COUNT=4457
b.FULL_PRODUCTION_EDGE_COUNT=8995
b.FULL_PRODUCTION_SEMANTIC_POINT_COUNT=4424
b.FULL_PRODUCTION_SOURCE_SHA='f5e20062c1400d7320fe2dbecf6409a0a8c910a7'
b.FULL_PRODUCTION_ADMISSION_SHA256='ec79a3cad1d84a936a6420b64c3ec43859ebd296eee992b2654dd8537d62da2d'
PY
printf '%s\n' 'import m26_e4_binding_overlay' > "$WORKDIR/00_m26_e4_binding_overlay.pth"
cat > "$WORKDIR/Dockerfile" <<'DOCKER'
FROM knowledge-engine:m26-public-api-staging-repair2-520aed
COPY m26_e4_binding_overlay.py /tmp/m26_e4_binding_overlay.py
COPY 00_m26_e4_binding_overlay.pth /tmp/00_m26_e4_binding_overlay.pth
RUN python -c "import pathlib,shutil,site; p=pathlib.Path(site.getsitepackages()[0]); shutil.copy2('/tmp/m26_e4_binding_overlay.py',p/'m26_e4_binding_overlay.py'); shutil.copy2('/tmp/00_m26_e4_binding_overlay.pth',p/'00_m26_e4_binding_overlay.pth')" && rm -f /tmp/m26_e4_binding_overlay.py /tmp/00_m26_e4_binding_overlay.pth
DOCKER
docker build --pull=false -t "$CANDIDATE_IMAGE" "$WORKDIR" >/dev/null

# Clone secrets from frozen base without printing them; override only candidate binding identity.
python3 - <<'PY'
import json, os, subprocess
base='m26-public-api-production-repair2-ownerhash-r2-auth-520aed'
env_path='/tmp/m26-e4-v3-candidate.env'
raw=json.loads(subprocess.run(['docker','inspect',base],text=True,capture_output=True,check=True).stdout)[0]['Config'].get('Env') or []
overrides={
 'M26_PA7_DENSE_COLLECTION':'m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440',
 'M26_ACCEPTED_RUNTIME_CANDIDATE':'520aeddb0566ca0ed1e2b74fa1fea1b7504a5e87',
}
rows=[]
for item in raw:
    if '=' not in item: continue
    name,_=item.split('=',1)
    if name in overrides: continue
    rows.append(item)
rows.extend(f'{k}={v}' for k,v in overrides.items())
with open(env_path,'w',encoding='utf-8') as f: f.write('\n'.join(rows)+'\n')
os.chmod(env_path,0o600)
PY

# --- Gate C: write only isolated candidate R2 bindings, never channels/production.json ---
docker run --rm -i --env-file "$ENVFILE" "$CANDIDATE_IMAGE" python - <<'PY'
import json
from knowledge_engine.config import Settings
from knowledge_engine.storage import create_object_store, sha256_bytes
release='m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440'
direct=f'releases/{release}/manifest.json'
promotion=f'candidate-bindings/{release}/promotion-manifest.json'
pointer=f'candidate-bindings/{release}/pointer.json'
expected_manifest='05e5f33e454e2ec5723223862b91729b9e4cb3f3c93068b5533eacae3e699796'
expected_pointer='5e4a2b995519fdae06b94bbcd5243ac8412c77b2e65b9286868ef58b7f06e574'
store=create_object_store(Settings.from_env())
data=store.get(direct)
if sha256_bytes(data)!=expected_manifest: raise SystemExit('M26_E4_V3_DIRECT_MANIFEST_DIGEST_MISMATCH')
manifest=json.loads(data)
if manifest.get('release_id')!=release: raise SystemExit('M26_E4_V3_DIRECT_MANIFEST_RELEASE_MISMATCH')
def ensure_exact(key,payload,digest):
    head=store.head(key)
    if head is None:
        store.put(key,payload,content_type='application/json',sha256=digest,only_if_absent=True)
    observed=sha256_bytes(store.get(key))
    if observed!=digest: raise SystemExit(f'M26_E4_V3_BINDING_OBJECT_DIGEST_MISMATCH key={key} expected={digest} observed={observed}')
ensure_exact(promotion,data,expected_manifest)
pointer_obj={'manifest_key':promotion,'manifest_sha256':expected_manifest,'release_id':release}
pointer_data=(json.dumps(pointer_obj,sort_keys=True,separators=(',',':'))+'\n').encode()
if sha256_bytes(pointer_data)!=expected_pointer: raise SystemExit('M26_E4_V3_POINTER_CONSTRUCTION_DIGEST_MISMATCH')
ensure_exact(pointer,pointer_data,expected_pointer)
print(json.dumps({'status':'M26_E4_V3_ISOLATED_BINDING_OBJECTS_PASS','release_id':release,'promotion_key':promotion,'manifest_sha256':expected_manifest,'pointer_key':pointer,'pointer_sha256':expected_pointer,'candidate_namespace_r2_objects':2,'production_pointer_writes':0,'canonical_route_mutations':0},sort_keys=True))
PY

PROD_POINTER_SHA_AFTER_BINDING="$(docker exec "$BASE_CONTAINER" python -c 'from knowledge_engine.config import Settings; from knowledge_engine.storage import create_object_store,sha256_bytes; print(sha256_bytes(create_object_store(Settings.from_env()).get("channels/production.json")))')"
test "$PROD_POINTER_SHA_AFTER_BINDING" = "$PROD_POINTER_SHA_BEFORE" || fail 'M26_E4_V3_PRODUCTION_POINTER_MUTATED_DURING_BINDING' 6

# --- Gate D: start isolated candidate on loopback-only 18088 ---
if docker ps -a --format '{{.Names}}' | grep -Fxq "$CANDIDATE_CONTAINER"; then
  docker rm -f "$CANDIDATE_CONTAINER" >/dev/null
fi
docker run -d --name "$CANDIDATE_CONTAINER" --restart unless-stopped --env-file "$ENVFILE" -p "127.0.0.1:${CANDIDATE_PORT}:8080" "$CANDIDATE_IMAGE" >/dev/null

for _ in $(seq 1 60); do
  if curl --fail --silent --max-time 3 "http://127.0.0.1:${CANDIDATE_PORT}/openapi.json" >"$OPENAPI"; then break; fi
  if ! docker inspect -f '{{.State.Running}}' "$CANDIDATE_CONTAINER" 2>/dev/null | grep -qx true; then
    docker logs --tail=200 "$CANDIDATE_CONTAINER" >&2 || true
    fail 'M26_E4_V3_CANDIDATE_EXITED' 7
  fi
  sleep 2
done
curl --fail --silent --max-time 5 "http://127.0.0.1:${CANDIDATE_PORT}/openapi.json" >"$OPENAPI" || { docker logs --tail=200 "$CANDIDATE_CONTAINER" >&2 || true; fail 'M26_E4_V3_HTTP_LIVENESS_FAIL' 7; }

python3 - <<'PY'
import json,pathlib
p=json.loads(pathlib.Path('/tmp/m26-e4-v3-openapi.json').read_text())
paths=sorted((p.get('paths') or {}).keys())
print(json.dumps({'status':'M26_E4_V3_HTTP_LIVENESS_PASS','paths':paths},sort_keys=True))
PY

# --- Gate E: candidate bytes identical to frozen base for semantic/translation/runtime modules ---
python3 - <<'PY'
import json, subprocess
base='m26-public-api-production-repair2-ownerhash-r2-auth-520aed'; cand='m26-e4-v3-candidate-180'
mods=['knowledge_engine.m26_aq_semantic_contract','knowledge_engine.m26_ask_api','knowledge_engine.m26_cloudflare_provider_router','knowledge_engine.m26_pa5_v8_live','knowledge_engine.m26_pa7_arbitrary_query_runtime','knowledge_engine.m26_production_answer_bundle','knowledge_engine.m26_production_api','knowledge_engine.m26_verified_answer_citation_gate','knowledge_engine.m26_multilingual_runtime','knowledge_engine.m26_translation_gateway','knowledge_engine.m26_translation_gateway_public_api','knowledge_engine.m26_translation_invariants']
code='''import importlib,hashlib,json,pathlib\nmods=%r\nout={}\nfor n in mods:\n p=pathlib.Path(importlib.import_module(n).__file__).resolve(); out[n]=hashlib.sha256(p.read_bytes()).hexdigest()\nprint(json.dumps(out,sort_keys=True))''' % mods
def hashes(c): return json.loads(subprocess.run(['docker','exec',c,'python','-c',code],text=True,capture_output=True,check=True).stdout)
a,b=hashes(base),hashes(cand)
if a!=b: raise SystemExit('M26_E4_V3_RUNTIME_BYTE_IDENTITY_FAIL '+json.dumps({'base':a,'candidate':b},sort_keys=True))
print(json.dumps({'status':'M26_E4_V3_RUNTIME_BYTE_IDENTITY_PASS','module_hashes':b},sort_keys=True))
PY

# --- Gate F: source/release/index binding, Qdrant read-only shape, no answer call ---
docker exec -i "$CANDIDATE_CONTAINER" python - <<'PY'
import json, os
import httpx
import knowledge_engine.m26_production_answer_bundle as b
expected={
 'release_id':'m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440',
 'manifest_key':'releases/m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440/manifest.json',
 'promotion_key':'candidate-bindings/m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440/promotion-manifest.json',
 'pointer_key':'candidate-bindings/m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440/pointer.json',
 'qdrant_collection':'m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440',
}
observed={'release_id':b.FULL_PRODUCTION_RELEASE_ID,'manifest_key':b.FULL_PRODUCTION_MANIFEST_KEY,'promotion_key':b.FULL_PRODUCTION_PROMOTION_MANIFEST_KEY,'pointer_key':b.FULL_PRODUCTION_POINTER_KEY,'qdrant_collection':b.FULL_PRODUCTION_QDRANT_COLLECTION}
if observed!=expected or os.environ.get('M26_PA7_DENSE_COLLECTION')!=expected['qdrant_collection']:
    raise SystemExit('M26_E4_V3_BINDING_RUNTIME_MISMATCH '+json.dumps({'expected':expected,'observed':observed},sort_keys=True))
bundle=b.load_production_answer_bundle()
report=b.build_production_answer_compatibility_report(bundle,qdrant_point_count=4424)
if bundle.release_id!=expected['release_id']: raise SystemExit('M26_E4_V3_BUNDLE_RELEASE_MISMATCH')
if report.get('status')!='compatible': raise SystemExit('M26_E4_V3_BUNDLE_COMPATIBILITY_FAIL '+json.dumps(report.get('mismatch_counts'),sort_keys=True))
qurl=os.environ['QDRANT_URL'].rstrip('/')+'/collections/'+expected['qdrant_collection']
headers={'api-key':os.environ['QDRANT_API_KEY'],'Accept':'application/json'}
r=httpx.get(qurl,headers=headers,timeout=30.0); r.raise_for_status(); result=(r.json() or {}).get('result') or {}
params=((result.get('config') or {}).get('params') or {}); vectors=params.get('vectors') or {}; default=vectors.get('default') or {}
shape={'status':result.get('status'),'points_count':result.get('points_count'),'indexed_vectors_count':result.get('indexed_vectors_count'),'vector_dimension':default.get('size'),'distance':default.get('distance'),'vector_name':'default' if default else None}
if shape['status']!='green' or shape['points_count']!=4424 or shape['vector_dimension']!=1024 or str(shape['distance']).casefold()!='cosine' or shape['vector_name']!='default':
    raise SystemExit('M26_E4_V3_QDRANT_READONLY_SHAPE_FAIL '+json.dumps(shape,sort_keys=True))
print(json.dumps({'status':'M26_E4_V3_BUNDLE_AND_QDRANT_BINDING_PASS','release_id':bundle.release_id,'manifest_sha256':bundle.manifest_sha256,'pointer_sha256':bundle.production_pointer_sha256,'promotion_manifest_sha256':bundle.production_manifest_sha256,'graph_nodes':len(bundle.graph_v2.get('nodes',[])),'graph_edges':len(bundle.graph_v2.get('edges',[])),'semantic_documents':len((bundle.semantic_inputs or {}).get('documents',[])),'qdrant':shape,'compatibility_status':report.get('status')},sort_keys=True))
PY

# Retrieval-universe addressability only. This deliberately does not call /api/m26/query or any provider.
docker exec -i "$CANDIDATE_CONTAINER" python - <<'PY'
import json
import knowledge_engine.m26_production_answer_bundle as b
bundle=b.load_production_answer_bundle(); rows=[]
for container_name,container in [('source_documents',bundle.source_documents or {}),('lexical_index',bundle.lexical_index or {})]:
  for key in ('documents','sources'):
    values=container.get(key)
    if not isinstance(values,list): continue
    for row in values:
      if not isinstance(row,dict): continue
      text=' '.join(str(row.get(k,'')) for k in ('source_id','title','section_title','description','body','excerpt','canonical_url','url')).casefold()
      if 'mcp' in text and ('stateless' in text or 'session' in text or '2026-07-28' in text):
        rows.append({'container':container_name,'source_id':row.get('source_id'),'section_id':row.get('section_id'),'title':row.get('title') or row.get('section_title')})
if not rows: raise SystemExit('M26_E4_V3_STATELESS_MCP_NOT_ADDRESSABLE')
print(json.dumps({'status':'M26_E4_V3_STATELESS_MCP_ADDRESSABILITY_PASS','match_count':len(rows),'sample':rows[:5]},sort_keys=True))
PY

# --- Gate G: production immutability after candidate start ---
PROD_POINTER_SHA_FINAL="$(docker exec "$BASE_CONTAINER" python -c 'from knowledge_engine.config import Settings; from knowledge_engine.storage import create_object_store,sha256_bytes; print(sha256_bytes(create_object_store(Settings.from_env()).get("channels/production.json")))')"
test "$PROD_POINTER_SHA_FINAL" = "$PROD_POINTER_SHA_BEFORE" || fail 'M26_E4_V3_PRODUCTION_POINTER_MUTATED' 8
test "$(docker inspect -f '{{.Id}}' "$BASE_CONTAINER")" = "$PROD_ID_BEFORE" || fail 'M26_E4_V3_PRODUCTION_CONTAINER_ID_MUTATED' 8
test "$(docker inspect -f '{{.Image}}' "$BASE_CONTAINER")" = "$BASE_IMAGE_ID" || fail 'M26_E4_V3_PRODUCTION_IMAGE_MUTATED' 8
test "$(docker inspect -f '{{.State.StartedAt}}' "$BASE_CONTAINER")" = "$PROD_STARTED_BEFORE" || fail 'M26_E4_V3_PRODUCTION_CONTAINER_RESTARTED' 8
test "$(docker inspect -f '{{.RestartCount}}' "$BASE_CONTAINER")" = "$PROD_RESTART_BEFORE" || fail 'M26_E4_V3_PRODUCTION_RESTART_COUNT_CHANGED' 8
test "$(docker port "$BASE_CONTAINER" 8080/tcp)" = '127.0.0.1:18087' || fail 'M26_E4_V3_PRODUCTION_PORT_MUTATED' 8
test "$(docker port "$CANDIDATE_CONTAINER" 8080/tcp)" = '127.0.0.1:18088' || fail 'M26_E4_V3_CANDIDATE_PORT_MISMATCH' 8

CANDIDATE_IMAGE_ID="$(docker inspect -f '{{.Image}}' "$CANDIDATE_CONTAINER")"
OVERLAY_SHA="$(docker exec "$CANDIDATE_CONTAINER" python -c 'import hashlib,m26_e4_binding_overlay,pathlib; print(hashlib.sha256(pathlib.Path(m26_e4_binding_overlay.__file__).read_bytes()).hexdigest())')"

python3 - <<PY
import json
print(json.dumps({
 'status':'E4_V3_ISOLATED_ORACLE_CANDIDATE_PASS',
 'candidate_container':'$CANDIDATE_CONTAINER',
 'candidate_host':'127.0.0.1',
 'candidate_port':18088,
 'candidate_image_id':'$CANDIDATE_IMAGE_ID',
 'frozen_base_image_id':'$BASE_IMAGE_ID',
 'accepted_runtime_identity':'$ACCEPTED_RUNTIME_ID',
 'semantic_contract_fingerprint':'$SEMANTIC_CONTRACT_FINGERPRINT',
 'binding_overlay_sha256':'$OVERLAY_SHA',
 'release_id':'$RELEASE_ID',
 'direct_manifest_sha256':'$DIRECT_MANIFEST_SHA',
 'candidate_pointer_sha256':'$CANDIDATE_POINTER_SHA',
 'qdrant_collection':'$QDRANT_COLLECTION',
 'source_count':180,
 'semantic_point_count':4424,
 'graph_node_count':4457,
 'graph_edge_count':8995,
 'e5_consumed_attempts':0,
 'provider_answer_requests':0,
 'candidate_namespace_r2_binding_writes_max':2,
 'production_pointer_writes':0,
 'canonical_route_mutations':0,
 'production_container_restarts':0,
 'production_port':18087,
},sort_keys=True))
PY
