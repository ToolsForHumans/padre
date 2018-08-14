# This is a separate thing because ansible importing makes all
# that it touches GPLv3; and we don't really want to have to make all
# the things GPLv3, so we'll just call this via subprocess from the bot
# code to decode things as needed.
#
# At some point when `ansible-decrypt` can actually decode inline ansible
# vault files fully we can likely just throw this away and use that
# instead (but until then, ya...).

import argparse
import json
import os

from ansible import constants as C
from ansible.parsing import dataloader
from ansible.parsing import vault
from ansible.parsing.yaml import objects


def _dictify(root):
    # Because ansible dataloader returns a lazy mapping (and decodes
    # on access, which is not really the behavior we always want, we want the
    # loading to die early if things can't be decrypted, not later...)
    if isinstance(root, objects.AnsibleVaultEncryptedUnicode):
        # Just accessing the property forces it to decrypt, weird...
        # but thats python for u.
        return root.data
    elif isinstance(root, (list, tuple, set)):
        n_list = []
        for v in list(root):
            n_list.append(_dictify(v))
        if isinstance(root, tuple):
            return tuple(n_list)
        if isinstance(root, set):
            return set(n_list)
        return n_list
    elif isinstance(root, (dict)):
        n_dict = {}
        for k, v in list(root.items()):
            n_dict[k] = _dictify(v)
        return n_dict
    else:
        return root


def _load_secrets(secrets_path, env_lookup_key=None):
    if not env_lookup_key:
        base, _ext = os.path.splitext(os.path.basename(secrets_path))
        path_key = "%s_PASS" % base.upper()
    else:
        path_key = env_lookup_key
    path_pass = os.getenv(path_key)
    if not path_pass:
        raise LookupError(
            "Unable to find password for '%s'"
            " under environment key '%s'" % (secrets_path, path_key))
    dl = dataloader.DataLoader()
    if hasattr(dl, 'set_vault_password'):
        dl.set_vault_password(path_pass)
    else:
        dl.set_vault_secrets([(C.DEFAULT_VAULT_IDENTITY,
                               vault.VaultSecret(path_pass))])
    return _dictify(dl.load_from_file(secrets_path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file",
                        help="secrets file to decode", required=True)
    parser.add_argument("-e", help="environment variable name/key to use to"
                                   " locate the password to the provided"
                                   " secrets file", required=False,
                        dest="env_lookup_key")
    args = parser.parse_args()
    secrets = _load_secrets(args.file, env_lookup_key=args.env_lookup_key)
    print(json.dumps(secrets))


if __name__ == '__main__':
    main()
