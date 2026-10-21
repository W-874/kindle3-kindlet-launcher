"""Behavioural regression tests for the precompiled template/AutoExit.class.

The real class is loaded into a temporary Java harness (tests/java). Only the
peer-dependent AWT state (showing / focus owner) and the KindletContext /
UIAdapter boundary types are simulated; the focus/queue/cancel state machine
under test is the shipped bytecode. Requires a JDK (javac + java); skipped
locally when absent, but a failure when the CI environment variable is set.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JAVA_DIR = ROOT / 'tests' / 'java'
HELPER = ROOT / 'template' / 'AutoExit.class'
HELPER_PACKAGE = pathlib.Path('com/mobileread/ixtab/kindlelauncher')
TIMEOUT = 60


class AutoExitBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.java = shutil.which('java')
        cls.javac = shutil.which('javac')
        if not (cls.java and cls.javac):
            if os.environ.get('CI'):
                raise AssertionError('CI must provide a JDK (java and javac) for AutoExit tests')
            raise unittest.SkipTest('JDK (java + javac) not available; AutoExit behaviour tests skipped')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.classes = pathlib.Path(cls.tmp.name) / 'classes'
        helper_dir = cls.classes / HELPER_PACKAGE
        helper_dir.mkdir(parents=True)
        shutil.copyfile(HELPER, helper_dir / 'AutoExit.class')
        sources = sorted(str(path) for path in (JAVA_DIR / 'stubs').rglob('*.java'))
        sources.append(str(JAVA_DIR / 'AutoExitHarness.java'))
        result = subprocess.run(
            [cls.javac, '-proc:none', '-nowarn', '-cp', str(cls.classes), '-d', str(cls.classes)] + sources,
            capture_output=True, text=True, timeout=TIMEOUT)
        if result.returncode != 0:
            raise AssertionError('harness compilation failed:\n' + result.stdout + result.stderr)

    def run_scenario(self, name):
        result = subprocess.run(
            [self.java, '-Xverify:all', '-Djava.awt.headless=true', '-cp', str(self.classes), 'AutoExitHarness', name],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=self.tmp.name)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        values = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('=')
            if separator:
                values[key] = value
        return values

    def test_without_focus_never_exits(self):
        values = self.run_scenario('no_focus_no_exit')
        self.assertEqual('0', values['calls'])
        # The listeners stay installed so a later focus can still trigger exit.
        self.assertEqual('1', values['armed.focusListeners'])
        self.assertEqual('1', values['armed.componentListeners'])

    def test_focus_exits_once_asynchronously(self):
        values = self.run_scenario('focus_exits_once_async')
        self.assertEqual('0', values['calls.beforeFocus'])
        self.assertEqual('0', values['calls.insideFocusEvent'])
        self.assertEqual('1', values['calls'])
        self.assertEqual('true', values['onEventThread'])
        self.assertEqual('0', values['after.focusListeners'])
        self.assertEqual('0', values['after.componentListeners'])

    def test_repeated_focus_does_not_repeat_exit(self):
        values = self.run_scenario('repeated_focus_exits_once')
        self.assertEqual('1', values['calls'])
        self.assertEqual('1', values['callsAfterExit'])

    def test_cancel_blocks_queued_exit_and_removes_listeners(self):
        values = self.run_scenario('cancel_queued_blocks_exit')
        self.assertEqual('0', values['calls'])
        self.assertEqual('0', values['after.focusListeners'])
        self.assertEqual('0', values['after.componentListeners'])
        self.assertEqual('0', values['callsAfterLateEvents'])

    def test_already_focused_target_schedules_exit_immediately(self):
        values = self.run_scenario('already_focused_schedules_immediately')
        self.assertEqual('0', values['calls.insideArm'])
        self.assertEqual('1', values['calls'])
        self.assertEqual('0', values['after.focusListeners'])
        self.assertEqual('0', values['after.componentListeners'])

    def test_focus_lost_before_exit_runs_then_regain_resumes(self):
        values = self.run_scenario('focus_lost_no_exit_then_regain')
        self.assertEqual('0', values['callsAfterLoss'])
        self.assertEqual('1', values['afterLoss.focusListeners'])
        self.assertEqual('1', values['afterLoss.componentListeners'])
        self.assertEqual('1', values['callsAfterRegain'])
        self.assertEqual('0', values['afterRegain.focusListeners'])
        self.assertEqual('0', values['afterRegain.componentListeners'])

    def test_hidden_target_does_not_exit_until_shown(self):
        values = self.run_scenario('hidden_no_exit_then_shown')
        self.assertEqual('0', values['callsWhileHidden'])
        self.assertEqual('1', values['hidden.focusListeners'])
        self.assertEqual('1', values['callsAfterShown'])
        self.assertEqual('0', values['shown.focusListeners'])


if __name__ == '__main__':
    unittest.main()
