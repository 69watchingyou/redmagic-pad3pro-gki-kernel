"""Offline consistency tests for the matched stock superproject manifest."""
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent / 'manifests'


class StockManifestTests(unittest.TestCase):
    def setUp(self):
        self.original = ET.parse(ROOT / 'stock-original.xml').getroot()
        self.pinned = ET.parse(ROOT / 'stock-pinned.xml').getroot()
        self.evidence = json.loads((ROOT / 'stock-snapshot.json').read_text())

    def test_all_34_gitlink_paths_and_names(self):
        projects = self.pinned.findall('project')
        paths = [p.get('path', p.get('name')) for p in projects]
        self.assertEqual(len(paths), 34)
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(set(paths), set(self.evidence['pins']))
        for p in projects:
            self.assertEqual(p.get('name'), self.evidence['project_names'][p.get('path')])
            self.assertEqual(p.get('revision'), self.evidence['pins'][p.get('path')])
            self.assertRegex(p.get('revision'), r'^[0-9a-f]{40}$')

    def test_no_moving_revision_or_relative_fetch(self):
        self.assertEqual(self.pinned.find('remote').get('fetch'), 'https://android.googlesource.com/')
        self.assertNotIn('revision', self.pinned.find('default').attrib)
        for element in self.pinned.iter():
            if 'revision' in element.attrib:
                self.assertRegex(element.get('revision'), r'^[0-9a-f]{40}$')
        self.assertEqual(self.pinned.find('superproject').get('revision'), '69fa47848cb1f63c3eb1db819a60befa8a644ec6')

    def test_stock_common_and_historical_manifest(self):
        self.assertEqual(self.evidence['manifest_commit'], 'e3beef2ebe3aae7684e49ea7e3bf135c7eefcddc')
        self.assertEqual(self.evidence['pins']['common'], '54dcbfbef792fe56756fa60d5f10395a958ac2f1')
        self.assertIn('not proof', self.evidence['confidence'])

    def test_original_semantics_preserved_except_pinning(self):
        original_projects = {p.get('path'): p for p in self.original.findall('project')}
        pinned_projects = {p.get('path'): p for p in self.pinned.findall('project')}
        self.assertEqual(set(original_projects), set(pinned_projects))
        for path, old in original_projects.items():
            new = pinned_projects[path]
            self.assertEqual({k:v for k,v in old.attrib.items() if k != 'revision'}, {k:v for k,v in new.attrib.items() if k != 'revision'})
            self.assertEqual([ET.tostring(c) for c in old], [ET.tostring(c) for c in new])
        self.assertEqual([(p.get('path'), c.attrib) for p in self.pinned.findall('project') for c in p.findall('linkfile')], [(p.get('path'), c.attrib) for p in self.original.findall('project') for c in p.findall('linkfile')])
        self.assertEqual(len(self.pinned.findall('.//linkfile')), 4)
        self.assertEqual(self.pinned.find("project[@path='kernel/tests']").findall('linkfile'), [])


if __name__ == '__main__':
    unittest.main()
