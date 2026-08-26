#!/usr/bin/env python3
from __future__ import annotations
import hashlib, importlib, inspect, json, pathlib, shutil, subprocess, sys

C='m26-e4-v3-oracle-isolated-m26blog-59012fe-520aed'
CID='3c5b31fa49daa9fbcfe3a438261801035a2be6538770f3950b52f11ced802bad'
IMG='sha256:7b2bdc32a3ed769f068b885e171fe31da10f33f1335b778b8bfb89ccb1523919'
AUTH='M26_QUERY_BACKEND_TOKEN'
MODULES=[
 'knowledge_engine.m26_translation_gateway_public_api',
 'knowledge_engine.m26_translation_gateway',
 'knowledge_engine.m26_ask_api',
 'knowledge_engine.m26_aq_semantic_contract',
 'knowledge_engine.m26_pa7_arbitrary_query_runtime',
 'knowledge_engine.m26_verified_answer_citation_gate',
 'knowledge_engine.m26_answer_evaluation',
 'knowledge_engine.m26_multilingual_publication_adapter',
]

def run(a,check=True): return subprocess.run(a,text=True,capture_output=True,check=check)
def sha(b): return hashlib.sha256(b).hexdigest()
def write(p,o): pathlib.Path(p).write_text(json.dumps(o,ensure_ascii=False,indent=2,sort_keys=True)+'\n')

def main():
 out=pathlib.Path('/tmp/m26-e5-repair1-contract-snapshot'); shutil.rmtree(out,ignore_errors=True); out.mkdir(parents=True)
 ins=json.loads(run(['docker','inspect',C]).stdout)[0]
 assert ins['Id']==CID, 'candidate id mismatch'; assert ins['Image']==IMG, 'image id mismatch'; assert ins['State']['Running'] is True, 'candidate not running'
 bindings=((ins.get('NetworkSettings') or {}).get('Ports') or {}).get('8080/tcp') or []
 assert any(x.get('HostIp')=='127.0.0.1' and x.get('HostPort')=='18187' for x in bindings), '18187 binding mismatch'
 env={}
 for row in (ins.get('Config') or {}).get('Env') or []:
  if '=' in row: k,v=row.split('=',1); env[k]=v
 assert env.get(AUTH), 'candidate auth source missing'
 write(out/'identity_auth_zero.json',{
  'container_id_exact':True,'image_id_exact':True,'running':True,'localhost_18187':True,
  'auth_env_key':AUTH,'auth_value_present':True,'auth_value_artifacted':False,'auth_value_logged':False,
  'semantic_posts':0,'e5_consumed':0,'rerolls':0,'production_mutations':0})
 code='''\nimport importlib,inspect,json\nmods=%r\nout=[]\nfor name in mods:\n try:\n  m=importlib.import_module(name); p=inspect.getsourcefile(m) or inspect.getfile(m)\n  out.append({"module":name,"path":p})\n except Exception as e:\n  out.append({"module":name,"error":type(e).__name__})\nprint(json.dumps(out,sort_keys=True))\n''' % MODULES
 cp=run(['docker','exec',C,'python','-c',code],check=False)
 if cp.returncode: raise SystemExit('module inventory failed:'+cp.stderr[-1000:])
 inventory=json.loads(cp.stdout.strip().splitlines()[-1]); write(out/'module_inventory.json',inventory)
 srcdir=out/'candidate_source'; srcdir.mkdir()
 manifest=[]
 for i,row in enumerate(inventory):
  p=row.get('path')
  if not p or not p.endswith('.py'): continue
  name=f'{i:02d}_{pathlib.Path(p).name}'; dest=srcdir/name
  cp=run(['docker','cp',f'{C}:{p}',str(dest)],check=False)
  if cp.returncode==0 and dest.is_file(): manifest.append({'module':row['module'],'container_path':p,'artifact_file':name,'sha256':sha(dest.read_bytes())})
 write(out/'source_manifest.json',{'files':manifest})
 code=r'''\nimport inspect,json\nfrom knowledge_engine.m26_translation_gateway_public_api import app,_answer_event_stream,_sse_event,_resolve_answer\nr=next(r for r in app.routes if getattr(r,'path',None)=='/v1/answers' and 'POST' in (getattr(r,'methods',set()) or set()))\nprint(json.dumps({\n "path":r.path,"methods":sorted(r.methods),\n "endpoint_module":r.endpoint.__module__,"endpoint_qualname":r.endpoint.__qualname__,\n "stream_generator_module":_answer_event_stream.__module__,\n "stream_generator_qualname":_answer_event_stream.__qualname__,\n "resolve_answer_module":_resolve_answer.__module__,\n "resolve_answer_qualname":_resolve_answer.__qualname__,\n "media_type_literal_present":"text/event-stream" in inspect.getsource(r.endpoint),\n "event_sequence_literals":[x for x in ["meta","progress","answer","done","error"] if ('\\"'+x+'\\"' in inspect.getsource(_answer_event_stream) or "'"+x+"'" in inspect.getsource(_answer_event_stream))],\n "semantic_posts":0\n},sort_keys=True))\n'''
 cp=run(['docker','exec',C,'python','-c',code],check=False)
 if cp.returncode: raise SystemExit('route structural snapshot failed:'+cp.stderr[-1000:])
 write(out/'route_structural_contract.json',json.loads(cp.stdout.strip().splitlines()[-1]))
 print('M26_E5_REPAIR1_CONTRACT_SNAPSHOT_PASS')
 print(json.dumps({'status':'M26_E5_REPAIR1_CONTRACT_SNAPSHOT_PASS','source_files':len(manifest),'semantic_posts':0,'e5_consumed':0,'rerolls':0,'production_mutations':0},sort_keys=True))
 return 0
if __name__=='__main__': raise SystemExit(main())
