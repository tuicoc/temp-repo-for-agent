"""Pinned real extractor process. Fixture extractor implementation hashes unchanged."""
import json
import os
from pathlib import Path
import subprocess

from .assets import parse_json, parse_json_block
from .extractor import extractor_input


class ModelExtractor:
    def __init__(self, assets, ref, manifest, recorder):
        if ref not in manifest["sources"]:raise ValueError("Extractor descriptor not pinned before Agent run")
        descriptor=assets.resolve(ref)
        if set(descriptor)!={"kind","version","python","backend","code","files","config","prompt","max_calls"} or descriptor["kind"]!="command_model":
            raise ValueError("Invalid real extractor descriptor")
        if descriptor["version"]!=manifest["configuration"]["extractor_version"]:raise ValueError("Extractor version mismatch")
        if type(descriptor["max_calls"]) is not int or not 1<=descriptor["max_calls"]<=64:
            raise ValueError("Extractor requires explicit pinned budget1–64; no unbounded permission")
        for source in [descriptor["code"],descriptor["prompt"],*descriptor["files"]]:
            if source not in manifest["sources"]:raise ValueError("Extractor dependencies/prompt must be pinned")
            assets.resolve(source,json_content=False)
        backend=(assets.root/descriptor["backend"]).resolve()
        if not backend.is_relative_to(assets.root) or assets.path(descriptor["code"]["path"])!=backend/"src/agents/evaluation_model.py":
            raise ValueError("Extractor backend/code path mismatch")
        self.assets,self.descriptor,self.descriptor_ref,self.version=assets,descriptor,ref,descriptor["version"]
        self.backend,self.recorder,self.calls=backend,recorder,0

    def replay(self, document):
        if self.calls>=self.descriptor["max_calls"]:raise ValueError("Real extractor model budget exhausted")
        self.calls+=1
        instructions=self.assets.resolve(self.descriptor["prompt"],json_content=False).read_text()
        payload={"config":self.descriptor["config"],"prompt":instructions+"\n[INPUT DATA]\n"+json.dumps(extractor_input(document),ensure_ascii=False)}
        # No GT/scenario/memory is transmitted to the extractor.
        try:
            env=dict(os.environ);env.pop("EVALUATION_APPROVAL_HMAC_KEY",None)
            # Snapshot has no .env; load backend credentials only inside the evaluator child.
            env_path=Path(self.descriptor["python"]).parent.parent.parent/".env"
            bootstrap=("from dotenv import load_dotenv; import runpy; "
                       "load_dotenv("+repr(str(env_path))+",override=False); "
                       "runpy.run_module('src.agents.evaluation_model',run_name='__main__')")
            result=subprocess.run([self.descriptor["python"],"-B","-c",bootstrap],cwd=self.backend,
                                  input=json.dumps(payload,ensure_ascii=False),text=True,capture_output=True,timeout=60,env=env)
            raw={"returncode":result.returncode,"stdout":result.stdout,"stderr":result.stderr}
            self.recorder(self.calls,raw)
            obj=parse_json(result.stdout)
            if result.returncode!=0 or obj.get("raw") is None:raise ValueError("Extractor provider/format error; raw attempt retained")
            parsed=parse_json_block(obj["raw"])
            if set(parsed)!={"items"} or not isinstance(parsed["items"],list):raise ValueError("Extractor needs items array")
            return parsed["items"]
        except subprocess.TimeoutExpired as exc:
            self.recorder(self.calls,{"returncode":None,"stdout":str(exc.stdout or ""),"stderr":"timeout; provider billing unreconciled"})
            raise ValueError("Extractor timeout; no retry") from exc
