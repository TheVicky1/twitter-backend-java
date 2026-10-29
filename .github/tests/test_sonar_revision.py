"""Exercise the fork workflow's revision guard without GitHub credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / 'workflows/sonar-fork.yml'
TEXT = WORKFLOW.read_text()
GUARD = TEXT[TEXT.index('          revision="$(cat'):]
GUARD = GUARD.split('      - name:', 1)[0]
GUARD = '\n'.join(line[10:] for line in GUARD.splitlines())
SHA = 'a' * 40
HEAD = 'b' * 40


class RevisionGuardTest(unittest.TestCase):
    def run_guard(self, artifact=SHA, current=SHA, fetched=SHA, parent=HEAD):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '_sonar-input').mkdir()
            (root / '_sonar-input/sonar-revision.txt').write_text(artifact + '\n')
            environment = dict(os.environ, CURRENT=current, FETCHED=fetched,
                               PARENT=parent, HEAD_SHA=HEAD,
                               HEAD_REPOSITORY='owner/fork', HEAD_BRANCH='feature',
                               BASE_BRANCH='master', REPOSITORY='owner/repo',
                               GITHUB_OUTPUT=str(root / 'output'))
            mocks = '''
            gh() {
              printf '[{"number":123,"head":{"repo":{"full_name":"owner/fork"},"sha":"%s","ref":"feature"},"base":{"ref":"master"},"merge_commit_sha":"%s"}]\\n' "$HEAD_SHA" "$CURRENT"
            }
            git() {
              case "$*" in
                *rev-parse*FETCH_HEAD^2*) echo "$PARENT" ;;
                *rev-parse*) echo "$FETCHED" ;;
                *checkout*) touch checkout-called ;;
              esac
            }
            '''
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', mocks + GUARD],
                                    cwd=root, env=environment, capture_output=True, text=True)
            output = (root / 'output').read_text() if (root / 'output').exists() else ''
            return result.returncode, output, (root / 'checkout-called').exists()

    def test_matching_build_sets_exact_status_revision(self):
        expected = (
            'number=123\n'
            f'head_sha={HEAD}\n'
            'head_ref=feature\n'
            'base_ref=master\n'
            f'merge_sha={SHA}\n'
        )
        self.assertEqual(self.run_guard(), (0, expected, True))

    def test_stale_invalid_or_racing_build_never_sets_status_revision(self):
        for arguments in ({'current': 'c' * 40}, {'artifact': '../bad'},
                          {'fetched': 'c' * 40}, {'parent': 'c' * 40}):
            with self.subTest(arguments=arguments):
                code, output, checkout = self.run_guard(**arguments)
                self.assertNotEqual(code, 0)
                self.assertNotIn('merge_sha=', output)
                self.assertFalse(checkout)

    def test_source_is_checked_out_from_validated_revision(self):
        pr_checker = Path(__file__).parents[1].joinpath('workflows/pr-checker.yml').read_text()
        self.assertIn(
            'git -C _sonar-safe checkout --detach "$revision"',
            TEXT,
        )
        self.assertNotIn('src/main/java/\n            src/test/java/', pr_checker)
        self.assertIn('find _sonar-safe/src/main/java _sonar-safe/src/test/java -type l', TEXT)
        self.assertIn('head_sha="$(jq -r \'.head.sha\' <<< "$pr_json")"', TEXT)
        self.assertIn('FETCH_HEAD^2)" != "$head_sha"', TEXT)
        self.assertNotIn('FETCH_HEAD^2)" != "$HEAD_SHA"', TEXT)
        self.assertNotIn('SONAR_TOKEN', pr_checker)
        self.assertIn('SonarSource/sonarqube-scan-action@', TEXT)


if __name__ == '__main__':
    unittest.main()
