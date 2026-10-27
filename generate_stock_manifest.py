"""Reconstruct a pinned manifest from a matched superproject snapshot, not CI proof."""
import argparse
import configparser
import json
import re
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

SUPER = '69fa47848cb1f63c3eb1db819a60befa8a644ec6'
MANIFEST = 'e3beef2ebe3aae7684e49ea7e3bf135c7eefcddc'
COMMON = '54dcbfbef792fe56756fa60d5f10395a958ac2f1'
ROOT = Path(__file__).resolve().parent


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, encoding='utf-8')


def generate(super_repo, manifest_repo):
    tree = git(super_repo, 'ls-tree', '-r', SUPER)
    pins = {}
    for line in tree.splitlines():
        meta, path = line.split('\t', 1)
        mode, kind, sha = meta.split()
        if mode == '160000':
            assert kind == 'commit' and re.fullmatch('[0-9a-f]{40}', sha)
            pins[path] = sha
    recorded = git(super_repo, 'show', SUPER + ':.supermanifest').strip().split()
    assert recorded == ['kernel/manifest', 'refs/heads/common-android15-6.6-2024-07', MANIFEST], recorded
    modules = configparser.ConfigParser()
    modules.read_string(git(super_repo, 'show', SUPER + ':.gitmodules'))
    names = {modules[s]['path']: s.removeprefix('submodule "').removesuffix('"') for s in modules.sections()}
    source = git(manifest_repo, 'show', MANIFEST + ':default.xml')
    root = ET.fromstring(source, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    projects = root.findall('project')
    paths = [p.get('path', p.get('name')) for p in projects]
    assert len(paths) == len(set(paths)), 'duplicate project paths'
    assert set(paths) == set(pins) == set(names), {'manifest_only': sorted(set(paths)-set(pins)), 'gitlink_only': sorted(set(pins)-set(paths))}
    assert pins['common'] == COMMON
    for p in projects:
        path = p.get('path', p.get('name'))
        assert p.get('name') == names[path], (path, p.get('name'), names[path])
        p.set('revision', pins[path])
    root.find('remote').set('fetch', 'https://android.googlesource.com/')
    root.find('default').attrib.pop('revision')
    root.find('superproject').set('revision', SUPER)
    root.insert(0, ET.Comment(' Matched superproject snapshot; NOT proof of the original CI complete manifest. '))
    ET.indent(root, space='  ')
    out = ROOT / 'manifests'
    out.mkdir(exist_ok=True)
    (out / 'stock-pinned.xml').write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\n')
    (out / 'stock-original.xml').write_text(source, encoding='utf-8', newline='\n')
    evidence = {'confidence': 'superproject matched snapshot; not proof of original CI complete manifest', 'superproject_commit': SUPER, 'manifest_commit': MANIFEST, 'common_commit': COMMON, 'project_count': len(pins), 'pins': pins, 'project_names': names}
    (out / 'stock-snapshot.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'projects': len(pins), 'manifest': str(out / 'stock-pinned.xml'), 'confidence': evidence['confidence']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--superproject', type=Path, default=ROOT.parent / 'redmagic-superproject')
    parser.add_argument('--manifest', type=Path, default=ROOT.parent / 'redmagic-manifest')
    args = parser.parse_args()
    generate(args.superproject, args.manifest)
