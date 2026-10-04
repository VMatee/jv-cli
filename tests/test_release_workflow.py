from pathlib import Path
import re
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/release.yml'


class ReleaseWorkflowPermissions(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding='utf-8')

    def job(self, name):
        match = re.search(r'^  ' + re.escape(name) + r':\n((?:^    .*\n|^\n)*)',
                          self.workflow, re.MULTILINE)
        self.assertIsNotNone(match, f'Missing release job: {name}')
        return match.group(1)

    def permissions(self, scope, indent):
        # Read the workflow's simple block/inline permission maps. Unknown forms
        # fail the contract rather than silently assuming inheritance.
        lines = scope.splitlines()
        for index, line in enumerate(lines):
            if not line.startswith(indent + 'permissions:'):
                continue
            value = line[len(indent + 'permissions:'):].strip()
            if value:
                inline = re.fullmatch(r'\{(.+)\}', value)
                self.assertIsNotNone(inline, 'Unsupported permission declaration')
                entries = [entry.strip() for entry in inline.group(1).split(',')]
            else:
                entries = []
                for entry in lines[index + 1:]:
                    if not entry.startswith(indent + '  '):
                        break
                    entries.append(entry[len(indent + '  '):])
            permissions = {}
            for entry in entries:
                match = re.fullmatch(r'([a-z-]+):\s*(read|write|none)', entry)
                self.assertIsNotNone(match, f'Unsupported permission entry: {entry}')
                self.assertNotIn(match.group(1), permissions)
                permissions[match.group(1)] = match.group(2)
            self.assertTrue(permissions)
            return permissions
        return None

    def effective_permissions(self, job):
        declared = self.permissions(job, '    ')
        return declared if declared is not None else self.permissions(self.workflow, '')

    def test_verify_gate_can_read_actions_with_least_privilege(self):
        verify = self.job('verify')
        self.assertIn('scripts/release_gate.py', verify)
        self.assertEqual(self.permissions(self.workflow, ''),
                         {'contents': 'read', 'actions': 'read'})
        self.assertEqual(self.effective_permissions(verify),
                         {'contents': 'read', 'actions': 'read'})

    def test_publish_gate_can_read_actions_and_write_release_contents(self):
        publish = self.job('publish')
        self.assertIn('scripts/release_gate.py', publish)
        self.assertEqual(self.effective_permissions(publish),
                         {'contents': 'write', 'actions': 'read'})


if __name__ == '__main__':
    unittest.main()
