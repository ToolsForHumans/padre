import functools
import inspect
import os
import pkgutil

from padre import handler

import importlib
import six

from oslo_utils import importutils
from oslo_utils import reflection
from oslo_utils import strutils


strict_bool_from_string = functools.partial(
    strutils.bool_from_string, strict=True)


def _cmp_triggers(t1, t2):
    t1_text = t1.text
    t2_text = t2.text
    if t1_text < t2_text:
        return -1
    if t1_text > t2_text:
        return 1
    return 0


def _find_classes(find_cls, mod, include_abstract=False):
    found = []
    for _name, member in reflection.get_members(mod):
        if (not inspect.isclass(member) or
                not issubclass(member, find_cls)):
            continue
        a_cls = member
        if include_abstract or not inspect.isabstract(a_cls):
            found.append(a_cls)
    return found


def sort_handlers(handlers):
    if not handlers:
        return handlers
    triggers = []
    triggers_to_handlers = {}
    tmp_handlers_no_triggers = []
    for h_cls in handlers:
        h_cls_triggers = h_cls.handles_what.get("triggers", [])
        if not h_cls_triggers:
            tmp_handlers_no_triggers.append(h_cls)
        else:
            triggers.extend(h_cls_triggers)
            for t in h_cls_triggers:
                if t in triggers_to_handlers:
                    e_h_cls = triggers_to_handlers[t]
                    raise RuntimeError(
                        "Duplicate trigger already registered to"
                        " handler '%s'" % reflection.get_class_name(e_h_cls))
                triggers_to_handlers[t] = h_cls
    if six.PY3:
        key_func = functools.cmp_to_key(_cmp_triggers)
        triggers = sorted(triggers, key=key_func)
    else:
        triggers = sorted(triggers, cmp=_cmp_triggers)
    # NOTE(harlowja): we need to ensure that triggers that share the same
    # prefix so that the longer prefix is first (so that it tries to be matched
    # before the smaller one).
    tmp_triggers = []
    for t1 in triggers:
        if not tmp_triggers:
            tmp_triggers.append(t1)
            continue
        t1_text = t1.text
        t1_idx = len(tmp_triggers) - 1
        while t1_idx > 0:
            t2 = tmp_triggers[t1_idx]
            t2_text = t2.text
            if t1_text.startswith(t2_text):
                t1_idx -= 1
            else:
                break
        tmp_triggers.insert(t1_idx + 1, t1)
    tmp_handlers = []
    for t in tmp_triggers:
        h_cls = triggers_to_handlers[t]
        if h_cls not in tmp_handlers:
            tmp_handlers.append(h_cls)
    return tmp_handlers + tmp_handlers_no_triggers


def get_handler(cls_name, include_abstract=False):
    a_cls = importutils.import_class(cls_name)
    if not issubclass(a_cls, handler.Handler):
        raise TypeError("Unexpected class %s found"
                        " during loading of %s (not a"
                        " handler)" % (a_cls, cls_name))
    if not include_abstract and inspect.isabstract(a_cls):
        return None
    else:
        return a_cls


def get_handlers(base_module, recurse=False, include_abstract=False):
    if isinstance(base_module, six.string_types):
        base_module = importutils.import_module(base_module)
    if not inspect.ismodule(base_module):
        raise TypeError("Module type expected, not '%s'" % type(base_module))
    base_module_name = base_module.__name__
    base_module_path = base_module.__file__
    finder = pkgutil.ImpImporter(path=os.path.dirname(base_module_path))
    found = _find_classes(handler.Handler, base_module)
    for (mod_name, is_pkg) in finder.iter_modules(base_module_name + "."):
        mod = importlib.import_module(mod_name)
        if recurse and is_pkg:
            next_up_func = functools.partial(
                get_handlers, recurse=True,
                include_abstract=include_abstract)
        else:
            next_up_func = functools.partial(
                _find_classes, handler.Handler,
                include_abstract=include_abstract)
        for cls in next_up_func(mod):
            if cls not in found:
                found.append(cls)
    return found
