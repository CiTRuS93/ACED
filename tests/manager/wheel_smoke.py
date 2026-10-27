"""Install a built wheel in isolation from checkout imports and exercise its assets."""

import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    wheel = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="aced-wheel-") as temporary:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                temporary,
                str(wheel),
            ],
            check=True,
        )
        code = """
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import aced
import cddai
from importlib.metadata import distribution
from aced.manager.demo import create_demo_app
import httpx
assert Path(aced.__file__).is_relative_to(sys.argv[1]), aced.__file__
assert Path(cddai.__file__).is_relative_to(sys.argv[1]), cddai.__file__
assert aced.Runtime is cddai.Runtime
assert distribution('aced').metadata['Name'] == 'aced'
assert {entry.name for entry in distribution('aced').entry_points} == {
    'aced', 'aced-manager-demo', 'cddai', 'cddai-manager-demo'
}
async def check():
    app = create_demo_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://127.0.0.1:8765') as client:
            response = await client.get('/')
            assert response.status_code == 200
            assert '<title>ACED' in response.text
            assets = Path(aced.__file__).parent / 'manager/static/assets'
            for asset in assets.iterdir():
                assert (await client.get('/assets/' + asset.name)).status_code == 200
            token = app.state.bootstrap_token
            response = await client.post('/api/session', json={'token': token},
                                         headers={'Origin': 'http://127.0.0.1:8765'})
            assert response.status_code == 200
            assert (await client.get('/api/context')).json()['demo'] is True
asyncio.run(check())
print('Installed-wheel assets and local session smoke test passed.')
"""
        subprocess.run([sys.executable, "-c", code, temporary], cwd=temporary, check=True)


if __name__ == "__main__":
    main()
