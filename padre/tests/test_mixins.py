import os
import shutil
import tempfile

from testtools import TestCase

from padre import mixins
from padre import template_utils


class TemplateUser(mixins.TemplateUser):
    def __init__(self, template_dirs, template_subdir=None):
        self.template_dirs = template_dirs
        self.template_subdir = template_subdir


class TemplateUserTest(TestCase):
    def setUp(self):
        super(TemplateUserTest, self).setUp()
        self.template_dirs = []
        self.template_dirs.append(tempfile.mkdtemp())
        with open(os.path.join(self.template_dirs[-1],
                               'blah.j2'), 'wb') as fh:
            fh.write(b"{{ blah }}")
        self.template_dirs.append(tempfile.mkdtemp())
        with open(os.path.join(self.template_dirs[-1],
                               'bing.j2'), 'wb') as fh:
            fh.write(b"{{ bing }}")

    def tearDown(self):
        super(TemplateUserTest, self).tearDown()
        while self.template_dirs:
            shutil.rmtree(self.template_dirs.pop())

    def test_subdir_not_exists(self):
        tu = TemplateUser(self.template_dirs, template_subdir='stuff')
        self.assertFalse(tu.template_exists("blah.j2"))
        self.assertFalse(tu.template_exists("blah"))
        self.assertFalse(tu.template_exists("bing.j2"))
        self.assertFalse(tu.template_exists("bing"))
        self.assertRaises(template_utils.MissingTemplate,
                          tu.render_template, "blah", {'blah': '1'})

    def test_exists(self):
        tu = TemplateUser(self.template_dirs)
        self.assertTrue(tu.template_exists("blah"))
        self.assertTrue(tu.template_exists("blah.j2"))
        self.assertFalse(tu.template_exists("blah_blah.j2"))

    def test_render(self):
        tu = TemplateUser(self.template_dirs)
        s = tu.render_template("blah", {'blah': '1'})
        self.assertEqual(s, '1')
        s = tu.render_template("blah.j2", {'blah': '1'})
        self.assertEqual(s, '1')

    def test_bad_render(self):
        tu = TemplateUser(self.template_dirs)
        self.assertRaises(template_utils.MissingTemplate,
                          tu.render_template, "blah_blah", {'blah': '1'})

    def test_exists_multi(self):
        tu = TemplateUser(self.template_dirs)
        self.assertTrue(tu.template_exists("bing"))
        self.assertTrue(tu.template_exists("bing.j2"))

    def test_multi_render(self):
        tu = TemplateUser(self.template_dirs)
        s = tu.render_template("bing", {'bing': '1'})
        self.assertEqual(s, '1')
        s = tu.render_template("bing.j2", {'bing': '1'})
        self.assertEqual(s, '1')
