import collections

import cachetools
import ldap
import munch


def explode_member(member, overwrite_same_keys=False):
    member_pieces = member.split(",")
    member = {}
    for piece in member_pieces:
        piece_pieces = piece.split("=", 1)
        if len(piece_pieces) == 1:
            k = piece_pieces[0]
            v = ""
        else:
            k = piece_pieces[0]
            v = piece_pieces[1].strip()
        if k in member:
            if overwrite_same_keys:
                member[k] = v
            else:
                if not isinstance(member[k], list):
                    member[k] = [member[k]]
                member[k].append(v)
        else:
            member[k] = v
    return member


class LdapClient(object):
    """Helper client that makes interacting with our ldap easier."""

    def __init__(self, uri, bind_dn, bind_password,
                 user_dn, service_user_dn, group_dn,
                 cache_size=512, cache_ttl=1800):
        self._uri = uri
        self._bind_dn = bind_dn
        self._bind_password = bind_password
        self._user_dn = user_dn
        self._service_user_dn = service_user_dn
        self._group_dn = group_dn
        self._service_user_filter_tpl = "(sAMAccountName=%(username)s)"
        self._group_list_filter_tpl = "(&(objectClass=group)(name=%(group)s))"
        self._user_filter_tpl = ("(&(objectClass=organizationalPerson)"
                                 "(!(objectClass=computer))"
                                 "(sAMAccountName=%(username)s))")
        # This avoids hammering ldap/ad for the same information all the time.
        self._cache = cachetools.TTLCache(cache_size, cache_ttl)

    def _make_ldap_client(self):
        ldap_client = ldap.initialize(self._uri)
        ldap_client.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        ldap_client.set_option(ldap.OPT_REFERRALS, False)
        ldap_client.simple_bind_s(self._bind_dn, self._bind_password)
        return ldap_client

    def whoami(self):
        cache_key = "me"
        try:
            return self._cache[cache_key]
        except KeyError:
            client = self._make_ldap_client()
            me = client.whoami_s()
            if me:
                self._cache[cache_key] = me
            return me

    def describe_user(self, user):
        def _get_result_key(result, k):
            try:
                return result[k][0]
            except (KeyError, IndexError):
                return None
        cache_key = "user:%s" % user
        try:
            real_user = self._cache[cache_key]
            return real_user.copy()
        except KeyError:
            client = self._make_ldap_client()
            finders = [
                (self._user_filter_tpl, self._user_dn),
                (self._service_user_filter_tpl, self._service_user_dn),
            ]
            real_user = None
            for filter_tpl, lookup_dn in finders:
                filter = filter_tpl % {'username': user}
                result = client.search_s(lookup_dn,
                                         ldap.SCOPE_SUBTREE, filter)
                if result:
                    _canon_user, result = result[0]
                    real_user = munch.Munch({
                        'street_address': _get_result_key(result,
                                                          'streetAddress'),
                        'name': _get_result_key(result, 'displayName'),
                        'unix_home_directory': _get_result_key(
                            result, "unixHomeDirectory"),
                        'employee_id': _get_result_key(result, 'employeeID'),
                        'uid': _get_result_key(result, 'uid'),
                        'principal_name': _get_result_key(result,
                                                          'userPrincipalName'),
                        'mail': _get_result_key(result, "mail"),
                        'description': _get_result_key(result, "description"),
                    })
                    break
            if real_user is not None:
                self._cache[cache_key] = real_user
                return real_user.copy()
            else:
                return real_user

    def list_ldap_group(self, group):
        cache_key = "group:%s" % group
        try:
            group_members = self._cache[cache_key]
            return group_members.copy()
        except KeyError:
            client = self._make_ldap_client()
            group_members = set()
            seen = set()
            group_list_filter_tpl = self._group_list_filter_tpl
            group_filter = group_list_filter_tpl % {'group': group}
            result = client.search_s(self._group_dn, ldap.SCOPE_SUBTREE,
                                     group_filter)
            if result:
                canon_group, result = result[0]
                if canon_group:
                    seen.add(canon_group)
                    scanning_members = collections.deque(result['member'])
                    while scanning_members:
                        member = scanning_members.popleft()
                        if member in seen:
                            continue
                        seen.add(member)
                        tmp_member = explode_member(
                            member, overwrite_same_keys=True)
                        member_cn = tmp_member.get("CN")
                        if not member_cn:
                            group_members.add(member)
                        else:
                            group_filter = group_list_filter_tpl % {
                                'group': member_cn,
                            }
                            result = client.search_s(self._group_dn,
                                                     ldap.SCOPE_SUBTREE,
                                                     group_filter)
                            if result:
                                canon_group, result = result[0]
                                if canon_group:
                                    seen.add(canon_group)
                                    scanning_members.extend(result['member'])
                                else:
                                    group_members.add(member)
                            else:
                                group_members.add(member)
            self._cache[cache_key] = group_members
            return group_members.copy()

    def is_allowed(self, username, ok_groupnames):
        if not ok_groupnames:
            return False
        canon_user_key = "user_canonicalized:%s" % username
        group_members = set()
        for groupname in ok_groupnames:
            group_members.update(self.list_ldap_group(groupname))
        try:
            canon_user = self._cache[canon_user_key]
        except KeyError:
            canon_user = None
            client = self._make_ldap_client()
            user_filter = self._user_filter_tpl % {'username': username}
            result = client.search_s(self._user_dn, ldap.SCOPE_SUBTREE,
                                     user_filter)
            if result:
                canon_user, _result = result[0]
                if canon_user:
                    self._cache[canon_user_key] = canon_user
        if canon_user and canon_user in group_members:
            return True
        return False

    def connect(self):
        self._make_ldap_client()
