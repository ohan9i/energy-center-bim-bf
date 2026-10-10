"""HTTP smoke check of a built Pages project path; does not execute browser JS."""
import argparse
import functools
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default='/bf-test/')
    args=parser.parse_args()
    base='/'+args.base.strip('/')+'/'
    dist=Path(__file__).resolve().parents[1]/'web'/'dist'
    html=(dist/'index.html').read_text(encoding='utf-8')
    references=re.findall(r'(?:src|href)="([^"]+)"',html)
    assets=[ref for ref in references if '/assets/' in ref]
    assert assets and all(ref.startswith(base+'assets/') for ref in assets), 'Build with the same VITE_BASE_PATH first.'
    assert not any(p.suffix.lower()=='.dwg' or p.name.startswith('energy-center') for p in dist.rglob('*')), 'Private drawing output found in static build.'
    with tempfile.TemporaryDirectory(prefix='bf-pages-check-') as temp:
        shutil.copytree(dist,Path(temp)/base.strip('/'))
        server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=temp))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        try:
            def get(path):
                with urlopen(origin+path,timeout=5) as r:
                    assert r.status==200
                    return r.read()
            get(base)
            demo=json.loads(get(base+'models/demo.json'));rules=json.loads(get(base+'rules.json'))
            assert demo['is_example'] and 'wheelchair' in rules['profiles']
            if (dist/'models'/'project.json').exists():
                project=json.loads(get(base+'models/project.json'))
                assert not project['is_example'] and len(project['floors'])==6
                assert project['provenance']['publication']=='github_pages'
                assert not any(e['verified'] for e in project['elements'])
            files=list((dist/'assets').iterdir())
            for file in files:get(base+'assets/'+file.name)
            workers=[p for p in files if p.name.startswith('route.worker-')]
            assert workers,'Route worker missing'
            js=''.join(p.read_text(encoding='utf-8') for p in files if p.suffix=='.js' and not p.name.startswith('route.worker-'))
            assert base+'assets/'+workers[0].name in js,'Worker reference ignores project base'
            print(f'PASS: {base} HTML, demo, rules, {len(files)} assets, worker URL; no private drawing output. Browser rendering not tested.')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

if __name__=='__main__':main()
