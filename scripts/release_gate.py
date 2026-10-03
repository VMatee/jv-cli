#!/usr/bin/env python3
"""Tag publication requires exact green main and no existing release."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request


def api(route):
    request = urllib.request.Request('https://api.github.com/' + route, headers={
        'User-Agent': 'JV-CLI-release-gate',
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    version = Path('VERSION').read_text(encoding='utf-8').strip()
    if not os.environ['GITHUB_REF'].startswith('refs/tags/'):
        print('Package rehearsal only; no publication')
        return
    tag = os.environ['GITHUB_REF_NAME']
    if tag != 'v' + version:
        raise RuntimeError('Tag differs from canonical VERSION')
    repo, commit = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']
    if api(f'repos/{repo}/branches/main')['commit']['sha'] != commit:
        raise RuntimeError('Tag must be exact accepted main')
    runs = api(f'repos/{repo}/actions/runs?head_sha={commit}&per_page=100')['workflow_runs']
    for name in ('JV CLI regression tests', 'JV CLI release'):
        matching = [r for r in runs if r['name'] == name and r['head_branch'] == 'main' and r['event'] == 'push']
        if not matching or matching[0]['status'] != 'completed' or matching[0]['conclusion'] != 'success':
            raise RuntimeError('Exact main regression/package gate is not green')
    try:
        api(f'repos/{repo}/releases/tags/{tag}')
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError('Could not check existing release') from None
    else:
        raise RuntimeError('Release exists; never replace published assets')
    print('PASS exact green main, canonical tag and absent release')


if __name__ == '__main__':
    main()
