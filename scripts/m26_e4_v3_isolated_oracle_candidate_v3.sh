#!/usr/bin/env bash
set -euo pipefail

BASE_CONTAINER='m26-public-api-production-repair2-ownerhash-r2-auth-520aed'
BASE_IMAGE='knowledge-engine:m26-public-api-staging-repair2-520aed'
BASE_IMAGE_ID='sha256:7b2bdc32a3ed769f068b885e171fe31da10f33f1335b778b8bfb89ccb1523919'
ACCEPTED_RUNTIME_ID='520aeddb0566ca0ed1e2b74fa1fea1b7504a5e87'
SEMANTIC_CONTRACT_FINGERPRINT='8d1a1f690c8e0d8ba5d39f772ce6146572286f2fe510a799e9848625e074128d'
CANDIDATE_CONTAINER='m26-e4-v3-candidate-180'
CANDIDATE_PORT='18088'
RELEASE_ID='m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440'
DIRECT_MANIFEST_SHA='05e5f33e454e2ec5723223862b91729b9e4cb3f3c93068b5533eacae3e699796'
CANDIDATE_POINTER_SHA='5e4a2b995519fdae06b94bbcd5243ac8412c77b2e65b9286868ef58b7f06e574'
QDRANT_COLLECTION='m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440'
OVERLAY_DIR="$HOME/.m26-e4-v3-candidate-overlay"
ENVFILE='/tmp/m26-e4-v3-candidate.env'
OPENAPI='/tmp/m26-e4-v3-openapi.json'

cleanup() { rm -f "$ENVFILE" "$OPENAPI"; }
trap cleanup EXIT
fail() { echo "$1" >&2; exit "${2:-1}"; }

# A. Freeze current production identity before any candidate-scoped write.
docker inspect "$BASE_CONTAINER" >/dev/null 2>&1 || fail 'M26_E4_V3_FROZEN_BASE_CONTAINER_MISSING' 3
test "$(docker inspect -f '{{.State.Running}}' "$BASE_CONTAINER")" = true || fail 'M26_E4_V3_FROZEN_BASE_CONTAINER_NOT_RUNNING' 3
test "$(docker inspect -f '{{.Image}}' "$BASE_CONTAINER")" = "$BASE_IMAGE_ID" || fail 'M26_E4_V3_BASE_IMAGE_ID_MISMATCH' 3
test "$(docker image inspect -f '{{.Id}}' "$BASE_IMAGE")" = "$BASE_IMAGE_ID" || fail 'M26_E4_V3_BASE_TAG_DRIFT' 3
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
import json,subprocess
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
'knowledge_engine.m26_translation_invariants':'a925ddaa756a60d7031936c0671c45b23893fa38d205722557bd1d98ad5c387c'}
code='''import importlib,hashlib,json,pathlib\nmods=%r\nout={}\nfor n in mods:\n p=pathlib.Path(importlib.import_module(n).__file__).resolve(); out[n]=hashlib.sha256(p.read_bytes()).hexdigest()\nprint(json.dumps(out,sort_keys=True))''' % list(frozen)
obs=json.loads(subprocess.run(['docker','exec',base,'python','-c',code],text=True,capture_output=True,check=True).stdout)
if obs!=frozen: raise SystemExit('M26_E4_V3_FROZEN_MODULE_HASH_MISMATCH '+json.dumps({'expected':frozen,'observed':obs},sort_keys=True))
print(json.dumps({'status':'M26_E4_V3_FROZEN_SEMANTIC_BYTES_PASS','module_hashes':obs},sort_keys=True))
PY

# B. Prepare persistent, read-only-at-runtime binding overlay. No image byte is modified.
rm -rf "$OVERLAY_DIR" && mkdir -p "$OVERLAY_DIR"
cat > "$OVERLAY_DIR/sitecustomize.py" <<'PY'
"""M26 E4 V3 binding-only startup overlay. Frozen semantic/translation modules remain untouched."""
import knowledge_engine.m26_production_answer_bundle as b
R='m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440'
b.FULL_PRODUCTION_RELEASE_ID=R
b.FULL_PRODUCTION_MANIFEST_KEY=f'releases/{R}/manifest.json'
b.FULL_PRODUCTION_PROMOTION_MANIFEST_KEY=f'candidate-bindings/{R}/promotion-manifest.json'
b.FULL_PRODUCTION_PROMOTION_MANIFEST_SHA256='05e5f33e454e2ec5723223862b91729b9e4cb3f3c93068b5533eacae3e699796'
b.FULL_PRODUCTION_GRAPH_V2_SHA256='d46022c9a4f50c939fd5f641b3073aee273a0cee690f4d7cadea2374698e2f14'
b.FULL_PRODUCTION_POINTER_KEY=f'candidate-bindings/{R}/pointer.json'
b.FULL_PRODUCTION_POINTER_SHA256='5e4a2b995519fdae06b94bbcd5243ac8412c77b2e65b9286868ef58b7f06e574'
b.FULL_PRODUCTION_QDRANT_COLLECTION='m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440'
b.FULL_PRODUCTION_NODE_COUNT=4457
b.FULL_PRODUCTION_EDGE_COUNT=8995
b.FULL_PRODUCTION_SEMANTIC_POINT_COUNT=4424
b.FULL_PRODUCTION_SOURCE_SHA='f5e20062c1400d7320fe2dbecf6409a0a8c910a7'
b.FULL_PRODUCTION_ADMISSION_SHA256='ec79a3cad1d84a936a6420b64c3ec43859ebd296eee992b2654dd8537d62da2d'
PY
chmod 755 "$OVERLAY_DIR"; chmod 644 "$OVERLAY_DIR/sitecustomize.py"
OVERLAY_SHA="$(sha256sum "$OVERLAY_DIR/sitecustomize.py" | awk '{print $1}')"

python3 - <<'PY'
import json,os,subprocess
base='m26-public-api-production-repair2-ownerhash-r2-auth-520aed'; env_path='/tmp/m26-e4-v3-candidate.env'
raw=json.loads(subprocess.run(['docker','inspect',base],text=True,capture_output=True,check=True).stdout)[0]['Config'].get('Env') or []
old={}
for item in raw:
    if '=' in item:
        k,v=item.split('=',1); old[k]=v
overrides={'M26_PA7_DENSE_COLLECTION':'m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440','M26_ACCEPTED_RUNTIME_CANDIDATE':'520aeddb0566ca0ed1e2b74fa1fea1b7504a5e87','PYTHONPATH':'/opt/m26-e4-overlay'+((':'+old['PYTHONPATH']) if old.get('PYTHONPATH') else '')}
rows=[]
for item in raw:
    if '=' not in item: continue
    k,_=item.split('=',1)
    if k in overrides: continue
    rows.append(item)
rows.extend(f'{k}={v}' for k,v in overrides.items())
with open(env_path,'w',encoding='utf-8') as f:f.write('\n'.join(rows)+'\n')
os.chmod(env_path,0o600)
PY

# C. Candidate-only R2 binding objects. Exact existing objects are reused; production pointer is forbidden.
docker run --rm -i --env-file "$ENVFILE" -v "$OVERLAY_DIR:/opt/m26-e4-overlay:ro" "$BASE_IMAGE" python - <<'PY'
import json
from knowledge_engine.config import Settings
from knowledge_engine.storage import create_object_store,sha256_bytes
release='m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440'; direct=f'releases/{release}/manifest.json'; promotion=f'candidate-bindings/{release}/promotion-manifest.json'; pointer=f'candidate-bindings/{release}/pointer.json'
em='05e5f33e454e2ec5723223862b91729b9e4cb3f3c93068b5533eacae3e699796'; ep='5e4a2b995519fdae06b94bbcd5243ac8412c77b2e65b9286868ef58b7f06e574'
store=create_object_store(Settings.from_env()); data=store.get(direct)
if sha256_bytes(data)!=em: raise SystemExit('M26_E4_V3_DIRECT_MANIFEST_DIGEST_MISMATCH')
manifest=json.loads(data)
if manifest.get('release_id')!=release: raise SystemExit('M26_E4_V3_DIRECT_MANIFEST_RELEASE_MISMATCH')
def ensure(key,payload,digest):
    if store.head(key) is None: store.put(key,payload,content_type='application/json',sha256=digest,only_if_absent=True)
    got=sha256_bytes(store.get(key))
    if got!=digest: raise SystemExit(f'M26_E4_V3_BINDING_OBJECT_DIGEST_MISMATCH key={key} expected={digest} observed={got}')
ensure(promotion,data,em)
pobj={'manifest_key':promotion,'manifest_sha256':em,'release_id':release}; pdata=(json.dumps(pobj,sort_keys=True,separators=(',',':'))+'\n').encode()
if sha256_bytes(pdata)!=ep: raise SystemExit('M26_E4_V3_POINTER_CONSTRUCTION_DIGEST_MISMATCH')
ensure(pointer,pdata,ep)
print(json.dumps({'status':'M26_E4_V3_ISOLATED_BINDING_OBJECTS_PASS','promotion_key':promotion,'pointer_key':pointer,'pointer_sha256':ep,'candidate_namespace_r2_objects':2,'production_pointer_writes':0,'canonical_route_mutations':0},sort_keys=True))
PY
PROD_POINTER_SHA_AFTER_BINDING="$(docker exec "$BASE_CONTAINER" python -c 'from knowledge_engine.config import Settings; from knowledge_engine.storage import create_object_store,sha256_bytes; print(sha256_bytes(create_object_store(Settings.from_env()).get("channels/production.json")))')"
test "$PROD_POINTER_SHA_AFTER_BINDING" = "$PROD_POINTER_SHA_BEFORE" || fail 'M26_E4_V3_PRODUCTION_POINTER_MUTATED_DURING_BINDING' 6

# D. Start isolated candidate from exact same frozen image on loopback-only :18088.
if docker ps -a --format '{{.Names}}' | grep -Fxq "$CANDIDATE_CONTAINER"; then docker rm -f "$CANDIDATE_CONTAINER" >/dev/null; fi
if ss -ltnH | awk '{print $4}' | grep -Eq "(^|:)${CANDIDATE_PORT}$"; then fail "M26_E4_V3_CANDIDATE_PORT_OCCUPIED port=$CANDIDATE_PORT" 7; fi
docker run -d --name "$CANDIDATE_CONTAINER" --restart unless-stopped --env-file "$ENVFILE" -v "$OVERLAY_DIR:/opt/m26-e4-overlay:ro" -p "127.0.0.1:${CANDIDATE_PORT}:8080" "$BASE_IMAGE" >/dev/null
for _ in $(seq 1 60); do
  if curl --fail --silent --max-time 3 "http://127.0.0.1:${CANDIDATE_PORT}/openapi.json" >"$OPENAPI"; then break; fi
  if ! docker inspect -f '{{.State.Running}}' "$CANDIDATE_CONTAINER" 2>/dev/null | grep -qx true; then docker logs --tail=200 "$CANDIDATE_CONTAINER" >&2 || true; fail 'M26_E4_V3_CANDIDATE_EXITED' 7; fi
  sleep 2
done
curl --fail --silent --max-time 5 "http://127.0.0.1:${CANDIDATE_PORT}/openapi.json" >"$OPENAPI" || { docker logs --tail=200 "$CANDIDATE_CONTAINER" >&2 || true; fail 'M26_E4_V3_HTTP_LIVENESS_FAIL' 7; }
python3 - <<'PY'
import json,pathlib
p=json.loads(pathlib.Path('/tmp/m26-e4-v3-openapi.json').read_text()); print(json.dumps({'status':'M26_E4_V3_HTTP_LIVENESS_PASS','paths':sorted((p.get('paths') or {}).keys())},sort_keys=True))
PY

# E. Exact same image and module bytes.
test "$(docker inspect -f '{{.Image}}' "$CANDIDATE_CONTAINER")" = "$BASE_IMAGE_ID" || fail 'M26_E4_V3_CANDIDATE_IMAGE_NOT_FROZEN_BASE' 8
python3 - <<'PY'
import json,subprocess
base='m26-public-api-production-repair2-ownerhash-r2-auth-520aed'; cand='m26-e4-v3-candidate-180'
mods=['knowledge_engine.m26_aq_semantic_contract','knowledge_engine.m26_ask_api','knowledge_engine.m26_cloudflare_provider_router','knowledge_engine.m26_pa5_v8_live','knowledge_engine.m26_pa7_arbitrary_query_runtime','knowledge_engine.m26_production_answer_bundle','knowledge_engine.m26_production_api','knowledge_engine.m26_verified_answer_citation_gate','knowledge_engine.m26_multilingual_runtime','knowledge_engine.m26_translation_gateway','knowledge_engine.m26_translation_gateway_public_api','knowledge_engine.m26_translation_invariants']
code='''import importlib,hashlib,json,pathlib\nmods=%r\nout={}\nfor n in mods:\n p=pathlib.Path(importlib.import_module(n).__file__).resolve(); out[n]=hashlib.sha256(p.read_bytes()).hexdigest()\nprint(json.dumps(out,sort_keys=True))''' % mods
def h(c): return json.loads(subprocess.run(['docker','exec',c,'python','-c',code],text=True,capture_output=True,check=True).stdout)
a,b=h(base),h(cand)
if a!=b: raise SystemExit('M26_E4_V3_RUNTIME_BYTE_IDENTITY_FAIL '+json.dumps({'base':a,'candidate':b},sort_keys=True))
print(json.dumps({'status':'M26_E4_V3_RUNTIME_BYTE_IDENTITY_PASS','module_hashes':b},sort_keys=True))
PY
CAND_FINGERPRINT="$(docker exec "$CANDIDATE_CONTAINER" python -c 'from knowledge_engine.m26_aq_semantic_contract import semantic_contract_fingerprint; print(semantic_contract_fingerprint())')"
test "$CAND_FINGERPRINT" = "$SEMANTIC_CONTRACT_FINGERPRINT" || fail 'M26_E4_V3_CANDIDATE_SEMANTIC_FINGERPRINT_DRIFT' 8

# F. Read-only bundle/Qdrant checks and retrieval-universe addressability. No answer endpoint/provider call.
docker exec -i "$CANDIDATE_CONTAINER" python - <<'PY'
import json,os,httpx
import knowledge_engine.m26_production_answer_bundle as b
release='m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440'; collection='m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440'
expected={'release_id':release,'manifest_key':f'releases/{release}/manifest.json','promotion_key':f'candidate-bindings/{release}/promotion-manifest.json','pointer_key':f'candidate-bindings/{release}/pointer.json','qdrant_collection':collection}
observed={'release_id':b.FULL_PRODUCTION_RELEASE_ID,'manifest_key':b.FULL_PRODUCTION_MANIFEST_KEY,'promotion_key':b.FULL_PRODUCTION_PROMOTION_MANIFEST_KEY,'pointer_key':b.FULL_PRODUCTION_POINTER_KEY,'qdrant_collection':b.FULL_PRODUCTION_QDRANT_COLLECTION}
if observed!=expected or os.environ.get('M26_PA7_DENSE_COLLECTION')!=collection: raise SystemExit('M26_E4_V3_BINDING_RUNTIME_MISMATCH '+json.dumps({'expected':expected,'observed':observed},sort_keys=True))
bundle=b.load_production_answer_bundle(); report=b.build_production_answer_compatibility_report(bundle,qdrant_point_count=4424)
if bundle.release_id!=release or report.get('status')!='compatible': raise SystemExit('M26_E4_V3_BUNDLE_COMPATIBILITY_FAIL '+json.dumps(report.get('mismatch_counts'),sort_keys=True))
r=httpx.get(os.environ['QDRANT_URL'].rstrip('/')+'/collections/'+collection,headers={'api-key':os.environ['QDRANT_API_KEY'],'Accept':'application/json'},timeout=30.0); r.raise_for_status(); result=(r.json() or {}).get('result') or {}; params=((result.get('config') or {}).get('params') or {}); default=((params.get('vectors') or {}).get('default') or {})
shape={'status':result.get('status'),'points_count':result.get('points_count'),'indexed_vectors_count':result.get('indexed_vectors_count'),'vector_dimension':default.get('size'),'distance':default.get('distance'),'vector_name':'default' if default else None}
if shape['status']!='green' or shape['points_count']!=4424 or shape['vector_dimension']!=1024 or str(shape['distance']).casefold()!='cosine' or shape['vector_name']!='default': raise SystemExit('M26_E4_V3_QDRANT_READONLY_SHAPE_FAIL '+json.dumps(shape,sort_keys=True))
rows=[]
for cname,container in [('source_documents',bundle.source_documents or {}),('lexical_index',bundle.lexical_index or {})]:
  for key in ('documents','sources'):
    vals=container.get(key)
    if not isinstance(vals,list): continue
    for row in vals:
      if not isinstance(row,dict): continue
      text=' '.join(str(row.get(k,'')) for k in ('source_id','title','section_title','description','body','excerpt','canonical_url','url')).casefold()
      if 'mcp' in text and ('stateless' in text or 'session' in text or '2026-07-28' in text): rows.append({'container':cname,'source_id':row.get('source_id'),'section_id':row.get('section_id'),'title':row.get('title') or row.get('section_title')})
if not rows: raise SystemExit('M26_E4_V3_STATELESS_MCP_NOT_ADDRESSABLE')
print(json.dumps({'status':'M26_E4_V3_NO_ANSWER_AUDIT_PASS','release_id':bundle.release_id,'manifest_sha256':bundle.manifest_sha256,'pointer_sha256':bundle.production_pointer_sha256,'promotion_manifest_sha256':bundle.production_manifest_sha256,'graph_nodes':len(bundle.graph_v2.get('nodes',[])),'graph_edges':len(bundle.graph_v2.get('edges',[])),'semantic_documents':len((bundle.semantic_inputs or {}).get('documents',[])),'qdrant':shape,'stateless_mcp_match_count':len(rows),'stateless_mcp_sample':rows[:5],'provider_answer_requests':0},sort_keys=True))
PY

# G. Prove production unchanged after candidate launch and audit.
PROD_POINTER_SHA_FINAL="$(docker exec "$BASE_CONTAINER" python -c 'from knowledge_engine.config import Settings; from knowledge_engine.storage import create_object_store,sha256_bytes; print(sha256_bytes(create_object_store(Settings.from_env()).get("channels/production.json")))')"
test "$PROD_POINTER_SHA_FINAL" = "$PROD_POINTER_SHA_BEFORE" || fail 'M26_E4_V3_PRODUCTION_POINTER_MUTATED' 9
test "$(docker inspect -f '{{.Id}}' "$BASE_CONTAINER")" = "$PROD_ID_BEFORE" || fail 'M26_E4_V3_PRODUCTION_CONTAINER_ID_MUTATED' 9
test "$(docker inspect -f '{{.Image}}' "$BASE_CONTAINER")" = "$BASE_IMAGE_ID" || fail 'M26_E4_V3_PRODUCTION_IMAGE_MUTATED' 9
test "$(docker inspect -f '{{.State.StartedAt}}' "$BASE_CONTAINER")" = "$PROD_STARTED_BEFORE" || fail 'M26_E4_V3_PRODUCTION_CONTAINER_RESTARTED' 9
test "$(docker inspect -f '{{.RestartCount}}' "$BASE_CONTAINER")" = "$PROD_RESTART_BEFORE" || fail 'M26_E4_V3_PRODUCTION_RESTART_COUNT_CHANGED' 9
test "$(docker port "$BASE_CONTAINER" 8080/tcp)" = '127.0.0.1:18087' || fail 'M26_E4_V3_PRODUCTION_PORT_MUTATED' 9
test "$(docker port "$CANDIDATE_CONTAINER" 8080/tcp)" = '127.0.0.1:18088' || fail 'M26_E4_V3_CANDIDATE_PORT_MISMATCH' 9

python3 - <<PY
import json
print(json.dumps({'status':'E4_V3_ISOLATED_ORACLE_CANDIDATE_PASS','candidate_container':'$CANDIDATE_CONTAINER','candidate_host':'127.0.0.1','candidate_port':18088,'candidate_image_id':'$BASE_IMAGE_ID','frozen_base_image_id':'$BASE_IMAGE_ID','accepted_runtime_identity':'$ACCEPTED_RUNTIME_ID','semantic_contract_fingerprint':'$SEMANTIC_CONTRACT_FINGERPRINT','binding_overlay_sha256':'$OVERLAY_SHA','release_id':'$RELEASE_ID','direct_manifest_sha256':'$DIRECT_MANIFEST_SHA','candidate_pointer_sha256':'$CANDIDATE_POINTER_SHA','qdrant_collection':'$QDRANT_COLLECTION','source_count':180,'semantic_point_count':4424,'graph_node_count':4457,'graph_edge_count':8995,'e5_consumed_attempts':0,'provider_answer_requests':0,'candidate_namespace_r2_binding_objects':2,'production_pointer_writes':0,'canonical_route_mutations':0,'production_container_restarts':0,'production_port':18087},sort_keys=True))
PY
