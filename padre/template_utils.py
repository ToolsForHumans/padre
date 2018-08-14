import os

from padre import utils


class MissingTemplate(Exception):
    pass


def _find_template_path(template_dir, template_name):
    if not os.path.isdir(template_dir):
        return None
    template_path = _form_template_path(template_dir, template_name)
    if not template_path:
        return None
    if os.path.isfile(template_path) and os.access(template_path, os.R_OK):
        return template_path
    else:
        return None


def _form_template_path(template_dir, template_name):
    template_dir = os.path.abspath(template_dir)
    if not template_name.endswith(".j2"):
        template_name += ".j2"
    template_path = os.path.join(template_dir, template_name)
    template_path = os.path.abspath(template_path)
    if not template_path.startswith(template_dir):
        return None
    return template_path


def find_template(template_dirs, template_name, template_subdir=None):
    for template_dir in template_dirs:
        if template_subdir:
            template_dir = os.path.join(template_dir, template_subdir)
        template_path = _find_template_path(template_dir, template_name)
        if template_path:
            return template_path
    raise MissingTemplate("Template '%s' could not"
                          " be found" % template_name)


def render_template(template_dirs, template_name,
                    template_params, **kwargs):
    template_path = find_template(
        template_dirs, template_name,
        template_subdir=kwargs.pop('template_subdir', None))
    with open(template_path, "rb") as fh:
        template_data = fh.read()
        return utils.render_template(template_data,
                                     template_params, **kwargs)
