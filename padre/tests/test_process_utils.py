from testtools import TestCase

from padre import process_utils as pu


class ProcessUtilsTest(TestCase):
    def test_run(self):
        r = pu.run(['bash', '-c', 'exit 0'])
        r.raise_for_status()
        self.assertEqual(r.exit_code, 0)

    def test_run_capture(self):
        r = pu.run(['bash', '-c', 'echo "hi"'],
                   stdout=pu.PIPE, stderr=pu.PIPE)
        r.raise_for_status()
        self.assertNotEqual("", r.stdout)

    def test_run_bad(self):
        r = pu.run(["bash", "-c", 'exit 1'], stdout=pu.PIPE, stderr=pu.PIPE)
        self.assertRaises(pu.ProcessExecutionError, r.raise_for_status)
        self.assertEqual(r.exit_code, 1)
